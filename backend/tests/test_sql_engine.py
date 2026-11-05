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
        tools._unregister_layer("长沙市")
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


def test_sql_values_statements_are_allowed():
    """只读 VALUES 表达式应被允许并可作为表输出。"""
    assert is_safe_readonly_sql("VALUES (1, '北京'), (2, '上海')")[0] is True

    res = execute_layer_sql("VALUES (1, '北京'), (2, '上海')", {})
    assert res["ok"] is True
    assert res["row_count"] == 2
    assert res["rows"] == [
        {"column1": 1, "column2": "北京"},
        {"column1": 2, "column2": "上海"},
    ]


def test_sql_markdown_table_escapes_pipes_and_newlines():
    """Markdown 表格输出应转义属性中的竖线并清理换行符，避免破坏表格排版。"""
    layers = {"pipe_layer": {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"title": "A | B", "desc": "line1\nline2"}, "geometry": None}
    ]}}
    res = execute_layer_sql('SELECT title, desc FROM "pipe_layer"', layers)
    assert res["ok"] is True
    table = res["markdown_table"]
    # 竖线被转义为 \|
    assert "A \\| B" in table
    # 单元格中的换行符被转为空格，不产生破坏性多行
    assert "line1 line2" in table
    # 表格有效行数保持为 3（表头、分割线、单条记录行）
    lines = [line for line in table.splitlines() if line.strip()]
    assert len(lines) == 3


def test_query_spatial_sql_disambiguates_repeated_output_names():
    """重复运行同名或默认输出名称的查询时，新图层应自动消歧并保留旧图层。"""
    from backend.services import tools
    tools.reset_state()
    source = "sql_disambiguate_src"
    destination = "sql_custom_result"
    try:
        tools._register_layer(source, {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [112.9, 28.2]},
                "properties": {"name": "点A"},
            }]
        })
        out1 = tools.query_spatial_sql.func(
            sql=f'SELECT * FROM "{source}"',
            result_layer_name=destination,
        )
        assert destination in tools._registered_layers

        out2 = tools.query_spatial_sql.func(
            sql=f'SELECT * FROM "{source}"',
            result_layer_name=destination,
        )
        assert f"{destination}_1" in tools._registered_layers
        assert destination in tools._registered_layers
        assert f"「{destination}_1」" in out2
    finally:
        tools._unregister_layer(source)
        tools._unregister_layer(destination)
        tools._unregister_layer(f"{destination}_1")
        tools.reset_state()


def test_sql_parenthesized_queries_are_allowed():
    """外层被圆括号包裹的只读查询应被正确识别并允许执行。"""
    assert is_safe_readonly_sql("(SELECT 1)")[0] is True
    assert is_safe_readonly_sql("  (  VALUES ('alpha')  )  ")[0] is True

    res = execute_layer_sql("(SELECT 1 AS num)", {})
    assert res["ok"] is True
    assert res["rows"] == [{"num": 1}]


def test_execute_layer_sql_handles_none_layers_and_malformed_features():
    """注册图层字典包含 None、非字典图层或要素列表含脏数据时不触发未捕获异常。"""
    layers = {
        "valid": {
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    None,
                    {"type": "Feature", "geometry": None, "properties": {"val": 100}},
                    "dirty_string_feature",
                ]
            }
        },
        "bad_none": None,
        "bad_str": "not_a_layer_dict",
    }
    res = execute_layer_sql('SELECT val FROM "valid" WHERE val = 100', layers)
    assert res["ok"] is True
    assert res["row_count"] == 1
    assert res["rows"][0]["val"] == 100


def test_large_json_integers_do_not_abort_queries_on_other_layers():
    """SQLite binding must not fail globally on exact JSON integers outside int64."""
    from backend.services.sql_engine import execute_layer_sql

    too_large = 2**63 + 17
    too_small = -(2**63) - 1
    layers = {
        "target": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"value": 7}, "geometry": None},
        ]},
        "unrelated_uint64": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"value": too_large}, "geometry": None},
            {"type": "Feature", "properties": {"value": too_small}, "geometry": None},
        ]},
    }

    target_result = execute_layer_sql('SELECT value FROM "target"', layers)
    assert target_result["ok"] is True
    assert target_result["rows"] == [{"value": 7}]

    large_result = execute_layer_sql('SELECT value FROM "unrelated_uint64"', layers)
    assert large_result["ok"] is True
    assert [row["value"] for row in large_result["rows"]] == [str(too_large), str(too_small)]


def test_query_spatial_sql_whitespace_name_falls_back_to_default():
    """空白字符作为 result_layer_name 时应回退到默认 SQL 过滤结果图层名，而非 fishnet。"""
    from backend.services import tools
    tools.reset_state()
    source = "sql_space_src"
    try:
        tools._register_layer(source, {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [112.9, 28.2]},
                "properties": {"name": "点1"},
            }]
        })
        out = tools.query_spatial_sql.func(
            sql=f'SELECT * FROM "{source}"',
            result_layer_name="   ",
        )
        assert "fishnet" not in tools._registered_layers
        # 默认名称应包含 SQL过滤结果
        assert any("SQL过滤结果" in k for k in tools._registered_layers.keys())
    finally:
        for k in list(tools._registered_layers.keys()):
            tools._unregister_layer(k)
        tools.reset_state()
