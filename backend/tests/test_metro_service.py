"""地铁服务回归：线路编号、OSM 类型隔离、方向合并及网络失败。"""
import io
import json

import pytest

from backend.services import metro_service as M


@pytest.fixture(autouse=True)
def empty_cache(monkeypatch):
    monkeypatch.setattr(M, "_cache", {})


def route_payload():
    # node、way、relation 的 ID 空间独立，特意使用相同 ID。
    nodes = [
        {"type": "node", "id": 42, "lon": 13.4, "lat": 52.5, "tags": {"name": "A"}},
        {"type": "node", "id": 43, "lon": 13.5, "lat": 52.6, "tags": {"name": "B"}},
    ]
    ways = [{"type": "way", "id": 42, "nodes": [42, 43]},
            {"type": "way", "id": 44, "nodes": [43, 42]}]
    relations = [{
        "type": "relation", "id": rel_id,
        "tags": {"ref": "M1", "name": f"M1 direction {i}", "colour": "#112233"},
        "members": [{"type": "way", "ref": way_id, "role": ""},
                    {"type": "node", "ref": 42, "role": "stop"},
                    {"type": "node", "ref": 43, "role": "stop"}],
    } for i, (rel_id, way_id) in enumerate(((42, 42), (44, 44)))]
    return relations, {"elements": relations + ways + nodes}


def install_routes(monkeypatch, payload=None, metadata=None):
    relations, full = route_payload()
    queries = []
    monkeypatch.setattr(M, "fetch_intl", lambda city: metadata if metadata is not None else relations)

    def fetch(query):
        queries.append(query)
        return payload if payload is not None else full

    monkeypatch.setattr(M, "_overpass_post", fetch)
    return queries


@pytest.mark.parametrize("city", M.CN_CITY_CODES)
def test_city_suffix_is_supported(city):
    assert M.norm_city(f" {city}市 ") == city


@pytest.mark.parametrize("name,query,expected", [
    ("M1", "M1", True), ("M1", "T1", False), ("M1", "M11", False),
    ("1A", "1B", False), ("地铁M1线", "Metro M1", True),
    ("11号线", "1号线", False), ("APM线", "APM", True),
])
def test_line_letters_are_part_of_the_number(name, query, expected):
    assert M.line_matches(name, query) is expected


def test_directions_are_batched_and_combined_without_losing_geometry(monkeypatch):
    queries = install_routes(monkeypatch)
    layers, summary = M.build_metro_layers("berlin", "M1")
    assert len(queries) == 1 and "relation(id:42,44)" in queries[0]
    assert len(layers) == 2
    lines = layers[0]["geojson"]["features"]
    assert len(lines) == 2
    assert lines[0]["geometry"]["coordinates"] == [[13.4, 52.5], [13.5, 52.6]]
    assert lines[1]["geometry"]["coordinates"] == [[13.5, 52.6], [13.4, 52.5]]
    assert len(layers[1]["geojson"]["features"]) == 2
    assert layers[1]["style"]["color"] == "#112233"
    assert "1 条线 2 站" in summary


def test_filter_and_dedup_happen_before_full_download(monkeypatch):
    relations, payload = route_payload()
    other = {"type": "relation", "id": 80, "tags": {"ref": "T1"}}
    queries = install_routes(monkeypatch, payload, [relations[0], relations[0], other])
    layers, _ = M.build_metro_layers("berlin", "M1")
    assert len(queries) == 1 and "relation(id:42)" in queries[0]
    assert len(layers[0]["geojson"]["features"]) == 1


def test_unmatched_line_does_not_download_geometry(monkeypatch):
    queries = install_routes(monkeypatch)
    with pytest.raises(ValueError, match="未找到匹配"):
        M.build_metro_layers("berlin", "T1")
    assert queries == []


def test_missing_direction_warns_and_does_not_invent_full_data(monkeypatch):
    _, payload = route_payload()
    payload["elements"] = [e for e in payload["elements"]
                           if not (e["type"] == "relation" and e["id"] == 44)]
    install_routes(monkeypatch, payload)
    layers, summary = M.build_metro_layers("berlin", "M1")
    assert len(layers[0]["geojson"]["features"]) == 1
    assert "1 个方向/分支获取失败" in summary and "可能不完整" in summary


def test_all_missing_directions_are_a_download_error(monkeypatch):
    install_routes(monkeypatch, {"elements": []})
    with pytest.raises(ValueError, match="匹配的线路方向/分支获取失败"):
        M.build_metro_layers("berlin", "M1")


@pytest.mark.parametrize("missing", ["way", "node", "coordinate"])
def test_incomplete_track_cannot_be_reported_as_complete(monkeypatch, missing):
    _, payload = route_payload()
    if missing == "coordinate":
        next(e for e in payload["elements"] if e["type"] == "node")["lon"] = float("nan")
    else:
        payload["elements"] = [e for e in payload["elements"]
                               if not (e["type"] == missing and e["id"] == 42)]
    install_routes(monkeypatch, payload)
    if missing == "way":
        layers, summary = M.build_metro_layers("berlin", "M1")
        assert len(layers[0]["geojson"]["features"]) == 1
        assert "可能不完整" in summary
    else:
        with pytest.raises(ValueError, match="匹配的线路方向/分支获取失败"):
            M.build_metro_layers("berlin", "M1")


def test_missing_middle_node_cannot_create_a_straight_shortcut():
    rels, payload = route_payload()
    next(e for e in payload["elements"] if e["type"] == "way")["nodes"] = [42, 999, 43]
    index = {(e["type"], str(e["id"])): e for e in payload["elements"]}
    assert M.intl_relation_to_features(rels[0], index) == []


def test_reversed_and_disconnected_track_parts_keep_their_geometry():
    rels, payload = route_payload()
    rels[0]["members"] += [{"type": "way", "ref": 45, "role": ""},
                           {"type": "way", "ref": 46, "role": ""}]
    payload["elements"] += [
        {"type": "node", "id": 47, "lon": 13.6, "lat": 52.6},
        {"type": "node", "id": 48, "lon": 13.8, "lat": 52.7},
        {"type": "node", "id": 49, "lon": 13.9, "lat": 52.8},
        {"type": "way", "id": 45, "nodes": [47, 43]},
        {"type": "way", "id": 46, "nodes": [48, 49]},
    ]
    index = {(e["type"], str(e["id"])): e for e in payload["elements"]}
    [(line, _, _)] = M.intl_relation_to_features(rels[0], index)
    assert line["geometry"] == {"type": "MultiLineString", "coordinates": [
        [[13.4, 52.5], [13.5, 52.6], [13.6, 52.6]], [[13.8, 52.7], [13.9, 52.8]],
    ]}


def test_network_failure_is_not_misreported_as_no_matching_line(monkeypatch):
    install_routes(monkeypatch)

    def fail(query):
        raise ValueError("Overpass 查询未完整完成")

    monkeypatch.setattr(M, "_overpass_post", fail)
    with pytest.raises(ValueError, match="未完整完成"):
        M.build_metro_layers("berlin", "M1")


def test_metadata_has_no_sixty_relation_cap_and_is_cached(monkeypatch):
    queries = []
    relations = [{"type": "relation", "id": i} for i in range(1, 82)]

    def fetch(query):
        queries.append(query)
        return {"elements": relations[:60] if "out tags 60" in query else relations}

    monkeypatch.setattr(M, "_overpass_post", fetch)
    assert len(M.fetch_intl("berlin")) == 81
    assert M.fetch_intl("berlin") == relations
    assert len(queries) == 1


def test_batch_survives_actual_tool_registration(monkeypatch):
    from backend.services import tools as T

    install_routes(monkeypatch)
    monkeypatch.setattr(T, "_registered_layers", {})
    monkeypatch.setattr(T, "_pending_layers", [])
    monkeypatch.setattr(T, "_pending_qa_warnings", [])
    result = T.metro_line.invoke({"city": "berlin", "line": "M1"})
    assert "已上图 2 个图层" in result
    assert len(T._pending_layers) == 2
    assert len(T._registered_layers["berlin地铁M1"]["geojson"]["features"]) == 2


@pytest.mark.parametrize("bad_payload", [[], {}, {"elements": [], "remark": "runtime error: timeout"}])
def test_overpass_rejects_invalid_or_incomplete_payloads(monkeypatch, bad_payload):
    import urllib.request

    monkeypatch.setattr(M, "_OVERPASS_HOSTS", ["example.invalid"])
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(bad_payload).encode()))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def json(self):
            return bad_payload

    monkeypatch.setattr(M.requests, "post", lambda *a, **k: Response())
    with pytest.raises(ValueError, match="Overpass 获取失败"):
        M._overpass_post("query")


def test_retry_uses_remaining_budget_and_stops_when_exhausted(monkeypatch):
    import urllib.request

    now = [0.0]
    calls = []
    monkeypatch.setattr(M.time, "monotonic", lambda: now[0])

    def fail(*args, timeout, **kwargs):
        calls.append(timeout)
        now[0] += 4
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    monkeypatch.setattr(M.requests, "post", fail)
    with pytest.raises(ValueError, match="等待超时"):
        M._overpass_post("query", timeout=6)
    assert calls == [6, 2]
