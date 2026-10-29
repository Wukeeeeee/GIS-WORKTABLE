"""Exercise real provider payload serialization with an in-process HTTP transport."""
from copy import deepcopy
import json
import math

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from backend.services import ai_service, graph, privacy_service as privacy, tools
from backend.services.llm_config import LLMConfig, ReasoningChatOpenAI


SECRET_LAYER = "内部设施_不外发"
SECRET_FIELD = "内部经济总量"
CITY_A = "北京保密站"
CITY_B = "上海保密站"


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_service, "_HISTORY_DIR", str(tmp_path / "history"))
    monkeypatch.setattr(privacy, "_vaults", {})
    monkeypatch.setattr(tools, "_registered_layers", {})
    for attr in ("_pending_layers", "_pending_images", "_pending_layer_ops", "_pending_qa_warnings", "_exec_log"):
        monkeypatch.setattr(tools, attr, [])
    monkeypatch.setattr(tools, "_current_task_id", None)
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [116.4074, 39.9042]},
         "properties": {"内部站点名称": CITY_A, SECRET_FIELD: 43760.7,
                        "内控备注": {"内部路径": "D:/confidential/站点.gpkg"}}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [121.4737, 31.2304]},
         "properties": {"内部站点名称": CITY_B, SECRET_FIELD: 47218.66}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [113.2644, 23.1291]},
         "properties": {"内部站点名称": "广州保密站", SECRET_FIELD: 30355.73}},
    ]}
    tools._register_layer(SECRET_LAYER, fc, sensitive=True)
    return fc


def model_transport(monkeypatch, decide):
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        content = decide(payload, len(requests))
        return httpx.Response(200, json={
            "id": "private-test", "object": "chat.completion", "created": 1,
            "model": "private-test", "choices": [{"index": 0, "message": content,
                                                        "finish_reason": "tool_calls" if content.get("tool_calls") else "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        })

    model = ReasoningChatOpenAI(model="private-test", api_key="test-key",
                               base_url="https://provider.example.test/v1",
                               http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr("backend.services.llm_config.build_llm", lambda cfg: model)
    return requests


def call(name, args, ident="call-1"):
    return {"role": "assistant", "content": "", "tool_calls": [{
        "id": ident, "type": "function", "function": {"name": name, "arguments": json.dumps(args)},
    }]}


def cfg():
    return LLMConfig(model="private-test", api_key="test-key", base_url="https://provider.example.test/v1")


def catalog(payload):
    return json.loads(payload["messages"][0]["content"].split("\n目录：", 1)[1])


def assert_no_raw(requests):
    encoded = json.dumps(requests, ensure_ascii=False)
    for raw in (SECRET_LAYER, SECRET_FIELD, CITY_A, CITY_B, "广州保密站", "内部站点名称", "内控备注", "内部路径",
                "D:/confidential", "116.4074", "39.9042", "121.4737", "31.2304",
                "43760.7", "47218.66", "30355.73", "旧任务源码秘密", "旧回复秘密"):
        assert raw not in encoded, raw


def test_catalog_and_known_references_are_tokenized(workspace):
    vault = privacy.Vault()
    vault.refresh()
    safe = vault.redact(f"按{SECRET_FIELD}排序{SECRET_LAYER}，选择{CITY_A}")
    assert SECRET_FIELD not in safe and SECRET_LAYER not in safe and CITY_A not in safe
    assert "F_" in safe and "L_" in safe and "P_" in safe
    assert "feature_count" not in json.dumps(vault.catalog)
    before = deepcopy(vault.catalog)
    vault.refresh()
    assert vault.catalog == before
    assert_no_raw([{"catalog": vault.catalog, "user": safe}])


def test_duplicate_fields_are_not_sent_and_re_registration_invalidates_old_handles(workspace):
    tools._register_layer("another_layer", {
        "type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {SECRET_FIELD: 123},
        }],
    })
    vault = privacy.Vault()
    vault.refresh()
    with pytest.raises(privacy.PrivacyBoundaryError, match="同名字段"):
        vault.redact(SECRET_FIELD)
    qualified = vault.redact(f"{SECRET_LAYER}的{SECRET_FIELD}")
    assert SECRET_LAYER not in qualified and SECRET_FIELD not in qualified
    assert "L_" in qualified and "F_" in qualified
    old_layer, old_point, old_field = next(iter(vault.layers)), next(iter(vault.points)), next(iter(vault.fields))
    tools._register_layer(SECRET_LAYER, {
        "type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]},
            "properties": {"new_field": "new_value"},
        }],
    })
    vault.refresh()
    assert old_layer not in vault.layers
    assert old_point not in vault.points
    assert old_field not in vault.fields
    current_points = list(vault.points)
    stale = privacy._execute(vault, "local_distance", {
        "first": old_point, "second": current_points[0],
    }, [])
    assert stale == {"status": "needs_clarification", "reason": "unknown_ambiguous_or_expired_reference"}


def test_layer_rename_rotates_registration_and_invalidates_handles(workspace):
    vault = privacy.Vault()
    vault.refresh()
    old_layer = next(iter(vault.layers))
    old_point = next(iter(vault.points))
    old_field = next(iter(vault.fields))
    old_registration = tools._registered_layers[SECRET_LAYER]["registration_token"]
    tools.layer_control.invoke({"action": "rename", "name": SECRET_LAYER, "new_name": "renamed_synthetic_layer"})
    assert tools._registered_layers["renamed_synthetic_layer"]["registration_token"] != old_registration
    vault.refresh()
    assert old_layer not in vault.layers
    assert old_point not in vault.points
    assert old_field not in vault.fields


def test_ambiguous_field_name_stops_before_provider_request(workspace, monkeypatch):
    tools._register_layer("another_layer", {
        "type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {SECRET_FIELD: 123},
        }],
    })
    requests = model_transport(monkeypatch, lambda *args: {"role": "assistant", "content": "不应到达"})
    result = privacy.run_private_agent(f"按{SECRET_FIELD}筛选", "ambiguous", cfg())
    assert result["execution_status"] == "needs_clarification"
    assert "重名字段" in result["response"]
    assert requests == []


@pytest.mark.parametrize("value", [500, "500"])
def test_known_numeric_values_remain_usable_as_local_parameters(workspace, value):
    tools._registered_layers[SECRET_LAYER]["geojson"]["features"][0]["properties"][SECRET_FIELD] = value
    vault = privacy.Vault()
    vault.refresh()
    token = vault.redact("500")
    assert token.startswith("V_")
    assert privacy._number(vault, token) == 500


def test_provider_boundary_blocks_plain_calls_without_http(workspace, monkeypatch):
    requests = model_transport(monkeypatch, lambda *args: {})
    model = __import__("backend.services.llm_config", fromlist=["build_llm"]).build_llm(cfg())
    with pytest.raises(privacy.PrivacyBoundaryError):
        model.invoke([HumanMessage(content=SECRET_LAYER)])
    assert requests == []


def test_provider_boundary_rejects_changed_payload(workspace):
    model = ReasoningChatOpenAI(model="test", api_key="test")
    approved = [HumanMessage(content="已打码")]
    with privacy.approved_request(approved, privacy.SCHEMAS):
        with pytest.raises(privacy.PrivacyBoundaryError):
            model._get_request_payload([HumanMessage(content=SECRET_LAYER)], tools=privacy.SCHEMAS)
        with pytest.raises(privacy.PrivacyBoundaryError):
            model._get_request_payload(approved, tools=[])


def test_distance_uses_true_coordinates_without_sending_result(workspace, monkeypatch):
    def decide(payload, count):
        if count == 1:
            user = payload["messages"][-1]["content"]
            import re
            points = re.findall(r"P_[a-f0-9]{16}", user)
            return call("local_distance", {"first": points[0], "second": points[1]})
        assert "distance_m" not in json.dumps(payload)
        return {"role": "assistant", "content": "点间距离已在本地计算。"}
    requests = model_transport(monkeypatch, decide)
    result = graph.run_agent([SystemMessage(content="旧任务源码秘密")], cfg(),
                             original_message=f"计算{CITY_A}和{CITY_B}的距离", session_id="distance")
    assert result["privacy_mode"] is True
    assert result.get("execution_status") != "error", result
    from pyproj import Geod
    expected = abs(Geod(ellps="WGS84").inv(116.4074, 39.9042, 121.4737, 31.2304)[2])
    assert result["privacy_results"][0]["distance_m"] == pytest.approx(expected)
    assert 1_000_000 < expected < 1_200_000
    assert "米" in result["response"]
    assert_no_raw(requests)


def test_local_ranking_preserves_names_and_marks_result(workspace, monkeypatch):
    def decide(payload, count):
        if count == 1:
            item = catalog(payload)[0]
            field = next(f["field"] for f in item["fields"] if f["types"] == ["number"])
            return call("local_rank", {"layer": item["layer"], "field": field, "limit": 2})
        return {"role": "assistant", "content": "已生成排名图层。"}
    requests = model_transport(monkeypatch, decide)
    result = privacy.run_private_agent(f"按{SECRET_FIELD}取前2名", "rank", cfg())
    assert result.get("execution_status") != "error", result
    assert len(result["layers"]) == 1
    derived = result["layers"][0]
    assert derived["sensitive"] is True
    assert [f["properties"]["内部站点名称"] for f in derived["geojson"]["features"]] == [CITY_B, CITY_A]
    assert tools._registered_layers[derived["name"]]["sensitive"] is True
    assert_no_raw(requests)


def test_real_500m_buffer_and_derived_protection(workspace, monkeypatch):
    tools._register_layer(SECRET_LAYER, {"type": "FeatureCollection", "features": workspace["features"][:1]})
    def decide(payload, count):
        if count == 1:
            return call("local_buffer", {"layer": catalog(payload)[0]["layer"], "radius_m": 500})
        return {"role": "assistant", "content": "缓冲区已生成。"}
    requests = model_transport(monkeypatch, decide)
    result = privacy.run_private_agent(f"给{SECRET_LAYER}做500米缓冲区", "buffer", cfg())
    assert result.get("execution_status") != "error", result
    assert len(result["layers"]) == 1, result
    derived = result["layers"][0]
    assert derived["sensitive"] is True
    assert derived["geojson"]["features"][0]["properties"]["内部站点名称"] == CITY_A
    import geopandas as gpd
    gdf = gpd.GeoDataFrame.from_features(derived["geojson"]["features"], crs="EPSG:4326")
    area = gdf.to_crs(gdf.estimate_utm_crs()).area.iloc[0]
    assert area == pytest.approx(math.pi * 500 ** 2, rel=.01)
    assert_no_raw(requests)


@pytest.mark.parametrize("operation", ["execute_python", "search_web", "export_map", "get_layer_detail"])
def test_forbidden_tools_cannot_run_or_return_data(workspace, monkeypatch, operation):
    def decide(payload, count):
        if count == 1:
            return call(operation, {"code": "open('private-file').read()"})
        tool_message = payload["messages"][-1]
        assert json.loads(tool_message["content"])["status"] == "blocked"
        return {"role": "assistant", "content": "该操作受限。"}
    requests = model_transport(monkeypatch, decide)
    result = privacy.run_private_agent("读取原始数据", "blocked-" + operation, cfg())
    assert result["layers"] == []
    assert len(requests) == 2
    assert_no_raw(requests)


def test_tool_failure_never_sends_exception_text(workspace, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError(SECRET_LAYER + " D:/confidential " + CITY_A)
    monkeypatch.setattr(tools.spatial_buffer, "func", explode)
    def decide(payload, count):
        if count == 1:
            return call("local_buffer", {"layer": catalog(payload)[0]["layer"], "radius_m": 500})
        assert json.loads(payload["messages"][-1]["content"])["status"] == "failed"
        return {"role": "assistant", "content": "本地操作失败。"}
    requests = model_transport(monkeypatch, decide)
    privacy.run_private_agent("做500米缓冲区", "error", cfg())
    assert len(requests) == 2
    assert_no_raw(requests)


def test_cancel_between_model_plan_and_local_tool_stops_without_retry(workspace, monkeypatch):
    checks = {"count": 0}
    def is_cancelled(*args):
        checks["count"] += 1
        return checks["count"] >= 2
    monkeypatch.setattr(ai_service, "is_session_cancelled", is_cancelled)
    def must_not_run(*args, **kwargs):
        pytest.fail("cancelled private tool must not execute")
    monkeypatch.setattr(tools.spatial_buffer, "func", must_not_run)
    requests = model_transport(monkeypatch, lambda payload, count: call(
        "local_buffer", {"layer": catalog(payload)[0]["layer"], "radius_m": 500}, "cancel-buffer"))
    result = privacy.run_private_agent("做500米缓冲区", "cancel-private", cfg())
    assert result.get("execution_status") == "cancelled"
    assert len(requests) == 1
    assert list(tools._registered_layers) == [SECRET_LAYER]
    assert_no_raw(requests)


def test_provider_timeout_does_not_retry_or_leak_and_releases_workspace_lock(workspace, monkeypatch):
    import httpx
    from backend.services import llm_config
    model = ReasoningChatOpenAI(model="timeout-test", api_key="synthetic-key")
    calls = {"count": 0}
    def timeout(self, *args, **kwargs):
        calls["count"] += 1
        raise httpx.ReadTimeout("SYNTHETIC_PROVIDER_TIMEOUT")
    monkeypatch.setattr(llm_config, "build_llm", lambda _cfg: model)
    monkeypatch.setattr(ReasoningChatOpenAI, "invoke", timeout)
    result = graph.run_agent([SystemMessage(content="untrusted old context")], cfg(),
                             original_message=f"读取{SECRET_LAYER}", session_id="timeout")
    assert result.get("execution_status") == "error"
    assert calls["count"] == 1
    assert model.max_retries == 0
    assert SECRET_LAYER not in result["response"]
    assert tools.acquire_shared_state_lock(0), "timeout leaked the shared workspace lock"
    tools.release_shared_state_lock()


def test_router_and_pending_shortcuts_are_not_used(workspace, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("ordinary router or saved action must not run")
    monkeypatch.setattr(ai_service, "_route_skills", forbidden)
    monkeypatch.setattr(ai_service, "_try_handle_confirm_command", forbidden)
    config = cfg()
    config.router = True
    content, skills, _ = ai_service._build_system_content(config, CITY_A, "router")
    assert CITY_A not in content and skills == ""
    assert ai_service._handle_pending_action_safely("router", "继续") is None


def test_private_sessions_stay_private_after_layer_removal_and_restart(workspace, monkeypatch):
    requests = model_transport(monkeypatch, lambda *args: {"role": "assistant", "content": "完成。"})
    privacy.run_private_agent("查看图层", "durable", cfg())
    tools._registered_layers.clear()
    privacy._vaults.clear()  # Simulate a process restart: only the marker survives.
    assert privacy.session_protected("durable") is True
    privacy.run_private_agent("继续", "durable", cfg())
    assert len(requests) == 1  # No workspace data remains to resolve references safely.
    assert_no_raw(requests)
    privacy.forget_session("durable")
    assert privacy.session_protected("durable") is False


def test_fixed_connectivity_probe_still_works_in_protected_mode(workspace, monkeypatch):
    requests = model_transport(monkeypatch, lambda *args: {"role": "assistant", "content": "ok"})
    success, _ = ai_service.test_key(cfg())
    assert success is True
    assert requests[0]["messages"] == [{"content": "hi", "role": "user"}]
    assert_no_raw(requests)


def test_session_aliases_are_separate(workspace):
    a, b = privacy.Vault(), privacy.Vault()
    a.refresh()
    b.refresh()
    assert a.catalog[0]["layer"] != b.catalog[0]["layer"]


@pytest.mark.parametrize("message", ['```python\nprint(data)\n```', '{"coordinates": [116.4074,39.9042]}'])
def test_raw_attachments_and_code_blocked_before_http(workspace, monkeypatch, message):
    requests = model_transport(monkeypatch, lambda *args: {})
    result = privacy.run_private_agent(message, "attachment", cfg())
    assert "不发送" in result["response"]
    assert requests == []


def test_stream_enters_the_same_protected_pipeline(workspace, monkeypatch):
    requests = model_transport(monkeypatch, lambda *args: {"role": "assistant", "content": "完成。"})
    events = list(graph.run_agent_stream([HumanMessage(content="旧回复秘密")], cfg(),
                                        original_message=f"查看{SECRET_LAYER}", session_id="stream"))
    done = json.loads(events[-1][6:])
    assert done["type"] == "done" and done["privacy_mode"] is True
    assert_no_raw(requests)


def test_registration_and_project_reset_preserve_privacy(workspace):
    snapshot = tools.get_registered_layers_snapshot()
    assert snapshot[0]["sensitive"] is True
    tools.reset_registered_layers(snapshot)
    assert tools._registered_layers[SECRET_LAYER]["sensitive"] is True
    tools._register_layer(SECRET_LAYER, workspace)
    assert tools._registered_layers[SECRET_LAYER]["sensitive"] is True
    tools._register_layer("派生图层", workspace)
    assert tools._registered_layers["派生图层"]["sensitive"] is True


def test_legacy_false_and_missing_flags_migrate_to_protected(workspace, monkeypatch):
    tools._registered_layers[SECRET_LAYER]["sensitive"] = False
    del tools._registered_layers[SECRET_LAYER]["sensitive"]
    assert privacy.workspace_protected() is True
    assert tools._registered_layers[SECRET_LAYER]["sensitive"] is True
    tools._registered_layers[SECRET_LAYER]["sensitive"] = False
    assert privacy.session_protected("legacy-migration") is True
    assert tools._registered_layers[SECRET_LAYER]["sensitive"] is True


def test_local_filter_statistics_and_style_keep_values_backend_only(workspace):
    vault = privacy.Vault()
    vault.refresh()
    layer = vault.catalog[0]["layer"]
    field = next(item["field"] for item in vault.catalog[0]["fields"] if item["types"] == ["number"])
    value = vault.replacements["43760.7"]
    local_results = []
    filtered = privacy._execute(vault, "local_filter", {
        "layer": layer, "field": field, "operator": "gte", "value": value,
    }, local_results)
    assert filtered["status"] == "ok"
    result_layer = filtered["layer"]
    result_layer_name = vault.layers[result_layer][0]
    assert tools._registered_layers[result_layer_name]["sensitive"] is True
    assert len(tools._registered_layers[result_layer_name]["geojson"]["features"]) == 2

    result_catalog = privacy._execute(vault, "local_catalog", {}, local_results)["catalog"]
    result_item = next(item for item in result_catalog if item["layer"] == result_layer)
    result_field = next(item["field"] for item in result_item["fields"] if item["types"] == ["number"])
    ranked = privacy._execute(vault, "local_rank", {
        "layer": result_layer, "field": result_field, "limit": 1, "descending": True,
    }, local_results)
    assert ranked["status"] == "ok"
    rank_layer_name = vault.layers[ranked["layer"]][0]
    top = tools._registered_layers[rank_layer_name]["geojson"]["features"][0]
    assert top["properties"]["内部站点名称"] == CITY_B

    stats = privacy._execute(vault, "local_statistics", {
        "layer": layer, "field": field,
    }, local_results)
    assert stats["status"] == "ok" and "statistics" not in json.dumps(stats)
    local_stats = next(item["statistics"] for item in local_results if item["operation"] == "statistics")
    assert local_stats["count"] == 3
    assert local_stats["max"] == pytest.approx(47218.66)

    style = privacy._execute(vault, "local_style", {
        "operation": "graduated", "layer": layer, "field": field, "classes": 3,
    }, local_results)
    assert style == {"status": "ok", "display": "style_applied"}
    assert tools.get_pending_state()["layer_ops"]


def test_local_overlay_uses_real_geometries_and_protects_result(workspace):
    square = lambda left, bottom, right, top: {
        "type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[
                [left, bottom], [right, bottom], [right, top], [left, top], [left, bottom],
            ]]}, "properties": {"secret_tag": f"SYNTHETIC_{left}"},
        }],
    }
    tools._register_layer("synthetic_a", square(0, 0, 2, 2))
    tools._register_layer("synthetic_b", square(1, 1, 3, 3))
    vault = privacy.Vault()
    vault.refresh()
    layer_a = next(alias for alias, (name, _) in vault.layers.items() if name == "synthetic_a")
    layer_b = next(alias for alias, (name, _) in vault.layers.items() if name == "synthetic_b")
    result = privacy._execute(vault, "local_overlay", {
        "operation": "intersect", "layer_a": layer_a, "layer_b": layer_b,
    }, [])
    assert result["status"] == "ok", result
    assert len(result["layers"]) == 1
    result_name, info = vault.layers[result["layers"][0]]
    assert info["sensitive"] is True
    assert len(info["geojson"]["features"]) == 1
    feature = info["geojson"]["features"][0]
    assert feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    assert "SYNTHETIC_" not in json.dumps(result)


@pytest.mark.parametrize("operation", ["clip", "union", "difference"])
def test_other_local_overlay_operations_create_protected_results(workspace, operation):
    square = lambda left, bottom, right, top: {
        "type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[
                [left, bottom], [right, bottom], [right, top], [left, top], [left, bottom],
            ]]}, "properties": {"synthetic_tag": f"SYNTH_{left}"},
        }],
    }
    tools._register_layer("overlay_subject", square(0, 0, 2, 2))
    tools._register_layer("overlay_mask", square(1, 1, 3, 3))
    vault = privacy.Vault()
    vault.refresh()
    aliases = {name: alias for alias, (name, _) in vault.layers.items()}
    result = privacy._execute(vault, "local_overlay", {
        "operation": operation, "layer_a": aliases["overlay_subject"], "layer_b": aliases["overlay_mask"],
    }, [])
    assert result["status"] == "ok", result
    assert result["layers"]
    assert all(vault.layers[alias][1]["sensitive"] is True for alias in result["layers"])


def test_local_spatial_selection_and_join_return_handles_only(workspace):
    tools._register_layer("synthetic_join", {
        "type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [116.4074, 39.9042]},
            "properties": {"joined_secret": "SYNTHETIC_JOIN_VALUE"},
        }],
    })
    vault = privacy.Vault()
    vault.refresh()
    aliases = {name: alias for alias, (name, _) in vault.layers.items()}
    selected = privacy._execute(vault, "local_spatial_select", {
        "target": aliases[SECRET_LAYER], "source": aliases[SECRET_LAYER], "predicate": "intersects",
    }, [])
    assert selected["status"] == "ok" and selected["layers"], selected
    joined = privacy._execute(vault, "local_spatial_join", {
        "target": aliases[SECRET_LAYER], "join": aliases["synthetic_join"],
        "how": "inner", "predicate": "intersects",
    }, [])
    assert joined["status"] == "ok", joined
    assert joined["layers"]
    assert "SYNTHETIC_JOIN_VALUE" not in json.dumps(selected)
    assert "SYNTHETIC_JOIN_VALUE" not in json.dumps(joined)
    assert all(info["sensitive"] is True for _, info in vault.layers.values())


def test_multistep_filter_rank_and_map_style_keep_payloads_tokenized(workspace, monkeypatch):
    def decide(payload, count):
        if count == 1:
            item = catalog(payload)[0]
            number_field = next(field["field"] for field in item["fields"] if field["types"] == ["number"])
            layer = item["layer"]
            return call("local_filter", {"layer": layer, "field": number_field,
                                          "operator": "gte", "value": "43000"}, "filter")
        if count == 2:
            return call("local_catalog", {}, "catalog")
        if count == 3:
            items = json.loads(payload["messages"][-1]["content"])["catalog"]
            derived = next(item for item in items if item["layer"] != catalog(payload)[0]["layer"])
            field = next(item["field"] for item in derived["fields"] if item["types"] == ["number"])
            return call("local_rank", {"layer": derived["layer"], "field": field,
                                        "limit": 1, "descending": True}, "rank")
        if count == 4:
            return call("local_catalog", {}, "catalog-ranked")
        if count == 5:
            items = json.loads(payload["messages"][-1]["content"])["catalog"]
            original = next(item for item in items if item["layer"] == catalog(payload)[0]["layer"])
            field = next(item["field"] for item in original["fields"] if item["types"] == ["number"])
            return call("local_style", {"operation": "graduated", "layer": original["layer"],
                                         "field": field, "classes": 3}, "style")
        if count == 6:
            original = catalog(payload)[0]
            field = next(item["field"] for item in original["fields"] if item["types"] == ["number"])
            return call("local_statistics", {"layer": original["layer"], "field": field}, "stats")
        return {"role": "assistant", "content": "筛选、排名和地图样式已完成。"}

    requests = model_transport(monkeypatch, decide)
    result = privacy.run_private_agent(f"筛选{SECRET_FIELD}大于等于43000，取排名并调整地图显示", "multi-step", cfg())
    assert result.get("execution_status") != "error", result
    assert len(result["layers"]) == 2, result
    assert all(layer["sensitive"] is True for layer in result["layers"])
    assert result["layer_ops"]
    assert result["privacy_results"][-1]["statistics"]["sum"] == pytest.approx(121335.09)
    assert "1.213e+05" in result["response"]
    assert "121335.09" not in json.dumps(requests)
    assert_no_raw(requests)


def test_privacy_setting_checks_layer_version_and_busy_workspace(workspace, monkeypatch):
    import asyncio
    from fastapi import HTTPException
    from backend import main
    token = tools._registered_layers[SECRET_LAYER]["registration_token"]
    with pytest.raises(HTTPException) as stale:
        asyncio.run(main.set_layer_privacy(main.LayerPrivacyRequest(
            name=SECRET_LAYER, sensitive=False, registration_token="stale")))
    assert stale.value.status_code == 409
    assert tools._registered_layers[SECRET_LAYER]["sensitive"] is True
    with pytest.raises(HTTPException) as downgrade:
        asyncio.run(main.set_layer_privacy(main.LayerPrivacyRequest(
            name=SECRET_LAYER, sensitive=False, registration_token=token)))
    assert downgrade.value.status_code == 409
    assert tools._registered_layers[SECRET_LAYER]["sensitive"] is True
    result = asyncio.run(main.set_layer_privacy(main.LayerPrivacyRequest(
        name=SECRET_LAYER, sensitive=True, registration_token=token)))
    assert result["sensitive"] is True
    monkeypatch.setattr(tools, "acquire_shared_state_lock", lambda *args: False)
    with pytest.raises(HTTPException) as busy:
        asyncio.run(main.set_layer_privacy(main.LayerPrivacyRequest(
            name=SECRET_LAYER, sensitive=True, registration_token=token)))
    assert busy.value.status_code == 409


def test_regular_registration_cannot_silently_remove_protection(workspace):
    import asyncio
    from backend import main
    result = asyncio.run(main.register_layer(main.RegisterLayerRequest(
        name=SECRET_LAYER, geojson=workspace, sensitive=False)))
    assert result["sensitive"] is True
    assert tools._registered_layers[SECRET_LAYER]["sensitive"] is True


def test_project_save_and_reopen_keep_protection(workspace, monkeypatch, tmp_path):
    from backend.services import project_service
    root = tmp_path / "projects"
    monkeypatch.setattr(project_service, "_PROJECT_DIR", str(root))
    monkeypatch.setattr(project_service, "_BLOB_DIR", str(root / "blobs"))
    monkeypatch.setattr(project_service, "_INDEX_PATH", str(root / "index.json"))
    monkeypatch.setattr(project_service, "_blob_refcount", {})
    monkeypatch.setattr(tools, "_active_project_id", None)
    project = project_service.save_project(
        project_id=None, name="privacy-test", session_id="persist", provider="test", map_state={}, messages=[],
        layers=[{"name": SECRET_LAYER, "geojson": workspace, "sensitive": False}])
    opened = project_service.open_project(project["id"])
    assert opened["layers"][0]["sensitive"] is True
    assert tools._registered_layers[SECRET_LAYER]["sensitive"] is True


def test_legacy_project_without_privacy_marker_activates_protected_history(workspace, monkeypatch, tmp_path):
    from backend.services import project_service
    root = tmp_path / "legacy-project"
    monkeypatch.setattr(project_service, "_PROJECT_DIR", str(root))
    monkeypatch.setattr(project_service, "_BLOB_DIR", str(root / "blobs"))
    monkeypatch.setattr(project_service, "_INDEX_PATH", str(root / "index.json"))
    monkeypatch.setattr(project_service, "_blob_refcount", {})
    tools._registered_layers.clear()
    legacy = {"sessionId": "legacy-project-session", "layers": [],
              "messages": [{"role": "assistant", "content": "legacy synthetic history"}]}
    project_service._activate_project_data("legacy", legacy)
    assert legacy["privacy_mode"] is True
    assert privacy.session_protected("legacy-project-session") is True


def test_project_history_stays_protected_even_without_layers(workspace, monkeypatch, tmp_path):
    from backend.services import project_service
    root = tmp_path / "empty-project"
    monkeypatch.setattr(project_service, "_PROJECT_DIR", str(root))
    monkeypatch.setattr(project_service, "_BLOB_DIR", str(root / "blobs"))
    monkeypatch.setattr(project_service, "_INDEX_PATH", str(root / "index.json"))
    monkeypatch.setattr(project_service, "_blob_refcount", {})
    project = project_service.save_project(
        project_id=None, name="protected-history", session_id="portable", provider="test", map_state={},
        messages=[{"role": "assistant", "content": CITY_A}], layers=[])
    tools._registered_layers.clear()
    privacy.forget_session("portable")
    assert not privacy.session_protected("portable")
    opened = project_service.open_project(project["id"])
    assert opened["privacy_mode"] is True
    assert privacy.session_protected("portable")


@pytest.mark.parametrize("stream", [False, True])
def test_task_rerun_privacy_request_cannot_fall_back_to_plain_chat(workspace, monkeypatch, stream):
    from fastapi.testclient import TestClient
    from backend import main
    tools._registered_layers.clear()
    requests = model_transport(monkeypatch, lambda *args: {"role": "assistant", "content": "should not run"})
    with TestClient(main.app) as client:
        response = client.post("/api/chat/stream" if stream else "/api/chat", json={
            "message": CITY_A, "session_id": "rerun-" + str(stream), "privacy_mode": True,
            "llm_config": {"model": "private-test", "api_key": "test", "base_url": "https://provider.example.test/v1"}})
    assert response.status_code == 200
    assert requests == []
    assert privacy.session_protected("rerun-" + str(stream))


@pytest.mark.parametrize("stream", [False, True])
def test_chat_http_routes_skip_raw_attachment_and_quote(workspace, monkeypatch, stream):
    from fastapi.testclient import TestClient
    from backend import main
    monkeypatch.setattr(main.project_service, "auto_save", lambda *args, **kwargs: None)
    requests = model_transport(monkeypatch, lambda *args: {"role": "assistant", "content": "受保护操作已完成。"})
    payload = {"message": f"查看{SECRET_LAYER}", "session_id": "http-" + str(stream),
               "llm_config": {"model": "private-test", "api_key": "test-key", "base_url": "https://provider.example.test/v1"},
               "pending_layer": {"name": "附件原文秘密", "geojson": workspace}, "quoted": "旧回复秘密"}
    with TestClient(main.app) as client:
        response = client.post("/api/chat/stream" if stream else "/api/chat", json=payload)
    assert response.status_code == 200, response.text
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert not any(event.get("type") == "error" for event in events), events
        result = next(event for event in events if event.get("type") == "done")
    else:
        result = response.json()
    assert result["privacy_mode"] is True
    assert result.get("execution_status") != "error", result
    assert requests
    assert tools.acquire_shared_state_lock(0), "SSE/request cleanup leaked the workspace lock"
    tools.release_shared_state_lock()
    assert "附件原文秘密" not in json.dumps(requests, ensure_ascii=False)
    assert_no_raw(requests)
