# -*- coding: utf-8 -*-
"""测试 SQL 执行引擎：只读拦截、属性查询统计、自动图层衍生"""

import pytest
from backend.services.sql_engine import execute_layer_sql, is_safe_readonly_sql


def test_sql_security_whitelist():
    # 合法查询
    assert is_safe_readonly_sql("SELECT * FROM schools")[0] is True
    assert is_safe_readonly_sql("WITH sub AS (SELECT id FROM a) SELECT * FROM sub")[0] is True

    # 恶意或写操作被拦截
    assert is_safe_readonly_sql("DROP TABLE schools")[0] is False
    assert is_safe_readonly_sql("DELETE FROM schools")[0] is False
    assert is_safe_readonly_sql("INSERT INTO schools VALUES (1)")[0] is False
    assert is_safe_readonly_sql("UPDATE schools SET name='x'")[0] is False
    assert is_safe_readonly_sql("SELECT * FROM schools; DROP TABLE x")[0] is False


def test_sql_query_aggregation():
    # 构造模拟图层
    fake_layers = {
        "schools": {
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [118.78, 32.04]},
                     "properties": {"name": "金陵中学", "district": "鼓楼区", "type": "公立"}},
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [118.79, 32.05]},
                     "properties": {"name": "南京一中", "district": "秦淮区", "type": "公立"}},
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [118.80, 32.06]},
                     "properties": {"name": "某民办高中", "district": "鼓楼区", "type": "民办"}},
                ]
            }
        }
    }

    # 执行聚合统计
    sql = 'SELECT "district", count(*) as "总数" FROM "schools" GROUP BY "district" ORDER BY "总数" DESC'
    res = execute_layer_sql(sql, fake_layers)
    assert res["ok"] is True
    assert res["row_count"] == 2
    assert "鼓楼区" in res["markdown_table"]
    assert "秦淮区" in res["markdown_table"]


def test_sql_query_with_reserved_fid_property():
    """图层已注入 _fid 时仍可查询属性列和空间列。"""
    fake_layers = {
        "长沙市": {
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": "p:430100",
                        "geometry": {"type": "Point", "coordinates": [112.9, 28.2]},
                        "properties": {"_fid": "p:430100", "name": "长沙市", "pop": 100, "pop_wan": 1000, "label": "长沙"},
                    }
                ],
            }
        }
    }

    res = execute_layer_sql(
        'SELECT name, pop, pop_wan, label FROM "长沙市" ORDER BY pop_wan DESC',
        fake_layers,
    )

    assert res["ok"] is True
    assert res["row_count"] == 1
    assert res["rows"][0]["name"] == "长沙市"


def test_query_spatial_sql_tool_handles_registered_layer_fid():
    """从工具入口验证自动注入的 _fid 不会破坏用户属性查询。"""
    from backend.services import tools

    tools.reset_state()
    tools._register_layer("长沙市", {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [112.9, 28.2]},
            "properties": {"name": "长沙市", "pop_wan": 1000},
        }],
    })
    try:
        result = tools.query_spatial_sql.func(
            sql='SELECT name, pop_wan FROM "长沙市" ORDER BY pop_wan DESC'
        )
    finally:
        tools.reset_state()

    assert "SQL 执行成功" in result
    assert "长沙市" in result
    assert "1000" in result


@pytest.mark.parametrize("reserved_name", ["_FID", "_Geom_Json"])
def test_sql_reserved_engine_columns_are_filtered_case_insensitively(reserved_name):
    fake_layers = {
        "case_reserved": {
            "geojson": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "id": "stable-id",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "properties": {reserved_name: "business-value", "name": "feature"},
                }],
            }
        }
    }

    result = execute_layer_sql('SELECT _fid, name FROM "case_reserved"', fake_layers)

    assert result["ok"] is True
    assert result["rows"] == [{"_fid": "stable-id", "name": "feature"}]


def test_sql_reports_case_only_duplicate_business_columns():
    fake_layers = {
        "case_collision": {
            "geojson": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "properties": {"Name": "A", "name": "a"},
                }],
            }
        }
    }

    result = execute_layer_sql('SELECT * FROM "case_collision"', fake_layers)

    assert result["ok"] is False
    assert "大小写冲突字段" in result["error"]


def test_sql_query_to_layer_derivation():
    # 包含 _geom_json 时自动生成新图层 GeoJSON
    fake_layers = {
        "points": {
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [120.0, 30.0]},
                     "properties": {"val": 100, "status": "active"}},
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [121.0, 31.0]},
                     "properties": {"val": 20, "status": "inactive"}},
                ]
            }
        }
    }

    # 过滤 val > 50 的要素并保留空间几何
    sql = 'SELECT * FROM "points" WHERE cast("val" as integer) > 50'
    res = execute_layer_sql(sql, fake_layers, create_result_layer=True)
    assert res["ok"] is True
    assert res["row_count"] == 1
    assert res["derived_geojson"] is not None
    assert len(res["derived_geojson"]["features"]) == 1
    feat = res["derived_geojson"]["features"][0]
    assert feat["geometry"]["coordinates"] == [120.0, 30.0]
    assert feat["properties"]["val"] == 100


def test_numeric_aggregation_comparison_and_sort_keep_json_types():
    layers = {"numbers": {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"value": value}, "geometry": None}
        for value in [2, 10, 100]
    ]}}
    largest = execute_layer_sql("SELECT MAX(value) AS largest FROM numbers", layers)
    assert largest["ok"] is True
    assert largest["rows"] == [{"largest": 100}]
    ordered = execute_layer_sql("SELECT value FROM numbers WHERE value > 9 ORDER BY value", layers)
    assert ordered["rows"] == [{"value": 10}, {"value": 100}]


def test_zero_feature_id_is_preserved_at_nonzero_position():
    layers = {"points": {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "first", "properties": {}, "geometry": None},
        {"type": "Feature", "id": 0, "properties": {}, "geometry": None},
    ]}}
    result = execute_layer_sql("SELECT _fid FROM points", layers)
    assert result["ok"] is True
    assert result["rows"] == [{"_fid": "first"}, {"_fid": "0"}]


def test_table_hash_suffix_collision_does_not_merge_or_fail():
    import hashlib
    collision = "A_B_" + hashlib.md5(b"A B").hexdigest()[:6]
    layers = {name: {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"source": name}, "geometry": None},
    ]} for name in ["A-B", collision, "A B"]}
    result = execute_layer_sql(f'SELECT source FROM "{collision}_2"', layers)
    assert result["ok"] is True
    assert result["rows"] == [{"source": "A B"}]


@pytest.mark.parametrize("sql", ["SELECT/**/1 AS n", "SELECT(1) AS n"])
def test_valid_select_token_boundaries(sql):
    result = execute_layer_sql(sql, {})
    assert result["ok"] is True
    assert result["rows"] == [{"n": 1}]


def test_comments_do_not_hide_write_statement():
    assert is_safe_readonly_sql("WITH a AS (SELECT 1) /* gap */ DELETE FROM points")[0] is False


def test_replace_scalar_function_is_readonly_but_statement_is_rejected():
    result = execute_layer_sql("SELECT REPLACE('update street', 'street', 'road') AS name", {})
    assert result["ok"] is True
    assert result["rows"] == [{"name": "update road"}]
    assert is_safe_readonly_sql("WITH a AS (SELECT 1) REPLACE INTO points VALUES (1)")[0] is False


def test_unbounded_recursive_query_is_interrupted(monkeypatch):
    from backend.services import sql_engine
    monkeypatch.setattr(sql_engine, "SQL_QUERY_TIMEOUT_SECONDS", 0)
    result = execute_layer_sql(
        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n) SELECT SUM(x) FROM n", {},
    )
    assert result["ok"] is False
    assert "已中断" in result["error"]


def test_row_limit_rejects_instead_of_returning_partial_success(monkeypatch):
    from backend.services import sql_engine
    monkeypatch.setattr(sql_engine, "SQL_MAX_RESULT_ROWS", 3)
    query = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<4) SELECT x FROM n"
    result = execute_layer_sql(query, {})
    assert result["ok"] is False
    assert result["rows"] == []
    limited = execute_layer_sql(query + " LIMIT 3", {})
    assert limited["ok"] is True
    assert limited["row_count"] == 3


def test_result_byte_limit_rejects_large_text(monkeypatch):
    from backend.services import sql_engine
    monkeypatch.setattr(sql_engine, "SQL_MAX_RESULT_BYTES", 8)
    result = execute_layer_sql("SELECT 'abcdefghijk' AS value", {})
    assert result["ok"] is False
    assert result["rows"] == []


def test_blob_allocation_is_bounded(monkeypatch):
    from backend.services import sql_engine
    monkeypatch.setattr(sql_engine, "SQL_MAX_VALUE_BYTES", 1024)
    result = execute_layer_sql("SELECT randomblob(2048) AS data", {})
    assert result["ok"] is False


def test_sql_tool_maps_numeric_result_with_requested_name():
    from backend.services import tools
    source, destination = "sql_numeric_source", "sql_numeric_result"
    tools.reset_state()
    try:
        tools._register_layer(source, {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"value": value},
             "geometry": {"type": "Point", "coordinates": [112 + index * 0.01, 28]}}
            for index, value in enumerate([2, 10, 100])
        ]})
        output = tools.query_spatial_sql.func(
            sql=f'SELECT * FROM "{source}" WHERE value > 9 ORDER BY value',
            result_layer_name=destination,
        )
        assert not tools._tool_result_failed("query_spatial_sql", output)
        layer = next(item for item in tools.get_pending_state()["layers"] if item["name"] == destination)
        features = layer["geojson"]["features"]
        assert [feature["properties"]["value"] for feature in features] == [10, 100]
        assert [feature["geometry"]["coordinates"] for feature in features] == [[112.01, 28], [112.02, 28]]
    finally:
        tools._unregister_layer(source)
        tools._unregister_layer(destination)
        tools.reset_state()


@pytest.mark.parametrize("raises", [False, True])
def test_sql_tool_failure_is_detected_and_does_not_push_layer(monkeypatch, raises):
    from backend.services import sql_engine, tools
    tools.reset_state()
    if raises:
        def broken_engine(*args, **kwargs):
            raise RuntimeError("engine unavailable")
        monkeypatch.setattr(sql_engine, "execute_layer_sql", broken_engine)
    try:
        output = tools.query_spatial_sql.func(sql="DROP TABLE points")
        assert tools._tool_result_failed("query_spatial_sql", output)
        assert tools.get_pending_state()["layers"] == []
    finally:
        tools.reset_state()
