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
    assert feat["properties"]["val"] == "100"
