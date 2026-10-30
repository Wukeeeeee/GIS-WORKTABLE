"""
网络分析模块测试
使用 3x3 人工网格路网验证最短路径、服务区、最近设施、吸附功能
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import pytest
import networkx as nx
from shapely.geometry import LineString

from backend.services.network_service import (
    build_graph_from_geojson,
    find_nearest_node,
    snap_to_network,
    shortest_route,
    service_area,
    closest_facilities,
    _haversine,
)


# ===== 3x3 网格路网 =====
# 坐标单位度，网格间距 0.005°
#    A --- B --- C
#    |     |     |
#    D --- E --- F
#    |     |     |
#    G --- H --- I
# 每条边为 LineString，两个方向都可通行

_NODES = {
    "A": (116.300, 39.900),
    "B": (116.305, 39.900),
    "C": (116.310, 39.900),
    "D": (116.300, 39.895),
    "E": (116.305, 39.895),
    "F": (116.310, 39.895),
    "G": (116.300, 39.890),
    "H": (116.305, 39.890),
    "I": (116.310, 39.890),
}

_EDGES = [
    ("A", "B"), ("B", "C"),   # 上横线
    ("D", "E"), ("E", "F"),   # 中横线
    ("G", "H"), ("H", "I"),   # 下横线
    ("A", "D"), ("D", "G"),   # 左纵线
    ("B", "E"), ("E", "H"),   # 中纵线
    ("C", "F"), ("F", "I"),   # 右纵线
]


def _build_grid_geojson():
    """生成 3x3 网格 GeoJSON"""
    features = []
    for src, dst in _EDGES:
        p1, p2 = _NODES[src], _NODES[dst]
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [list(p1), list(p2)],
            },
            "properties": {},
        })
    return {"type": "FeatureCollection", "features": features}


GRID_GEOJSON = _build_grid_geojson()


# ============================================================
# 测试 build_graph_from_geojson
# ============================================================

class TestBuildGraph:
    def test_build_graph_has_nodes(self):
        g = build_graph_from_geojson(GRID_GEOJSON)
        assert g.number_of_nodes() == 9





# ============================================================
# 测试 find_nearest_node
# ============================================================

class TestFindNearestNode:
    def test_find_nearest_exact(self):
        g = build_graph_from_geojson(GRID_GEOJSON)
        node = find_nearest_node(g, _NODES["E"], max_dist=1000)
        assert node == _NODES["E"]





# ============================================================
# 测试 snap_to_network
# ============================================================

class TestSnapToNetwork:
    def test_snap_exact(self):
        result = snap_to_network(GRID_GEOJSON, _NODES["B"])
        assert result["found"] is True
        assert result["snapped"] == list(_NODES["B"])




# ============================================================
# 测试 shortest_route
# ============================================================

class TestShortestRoute:
    def test_route_adjacent(self):
        result = shortest_route(GRID_GEOJSON, _NODES["A"], _NODES["B"])
        assert "error" not in result
        assert 400 < result["distance_m"] < 600  # 水平边约 426m
        assert result["node_count"] == 2

    def test_rejects_network_coordinates_outside_wgs84(self):
        roads = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {},
             "geometry": {"type": "LineString", "coordinates": [[181, 0], [182, 0]]}},
        ]}

        with pytest.raises(ValueError, match="EPSG:4326"):
            shortest_route(roads, (181, 0), (182, 0))

    def test_rejects_route_points_outside_wgs84(self):
        with pytest.raises(ValueError, match="EPSG:4326"):
            shortest_route(GRID_GEOJSON, (181, 0), _NODES["A"])

    def test_network_api_returns_validation_error_instead_of_route(self):
        from fastapi.testclient import TestClient
        from backend.main import app

        roads = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {},
             "geometry": {"type": "LineString", "coordinates": [[181, 0], [182, 0]]}},
        ]}
        response = TestClient(app).post("/api/network/solve", json={
            "geojson": roads, "type": "route", "origin": [181, 0], "dest": [182, 0],
        })

        assert response.status_code == 200
        assert "EPSG:4326" in response.json()["error"]
        assert "path" not in response.json()

    def test_same_snapped_node_returns_zero_distance_point_feature(self):
        result = shortest_route(GRID_GEOJSON, _NODES["A"], _NODES["A"])

        assert "error" not in result
        assert result["path"]["geometry"] == {"type": "Point", "coordinates": list(_NODES["A"])}
        assert result["distance_m"] == 0
        assert result["distance_km"] == 0
        assert result["steps"] == []
        assert result["node_count"] == 1
        assert result["segments"][0]["distance_m"] == 0

    @pytest.mark.parametrize("bidirectional", [True, False])
    def test_route_respects_oneway_in_feature_coordinate_order(self, bidirectional):
        start, end = (0, 0), (0.01, 0)
        roads = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"oneway": "yes"},
             "geometry": {"type": "LineString", "coordinates": [start, end]}}
        ]}

        forward = shortest_route(roads, start, end, bidirectional=bidirectional)
        reverse = shortest_route(roads, end, start, bidirectional=bidirectional)

        assert "error" not in forward
        assert [tuple(point) for point in forward["path"]["geometry"]["coordinates"]] == [start, end]
        assert "error" in reverse

    def test_reverse_oneway_and_non_route_graphs_keep_their_existing_direction_policy(self):
        start, end = (0, 0), (0.01, 0)
        roads = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"oneway": "-1"},
             "geometry": {"type": "LineString", "coordinates": [start, end]}}
        ]}

        reverse = shortest_route(roads, end, start)
        forward = shortest_route(roads, start, end)

        assert "error" not in reverse
        assert "error" in forward
        assert set(build_graph_from_geojson(roads).edges) == {(start, end), (end, start)}

    @pytest.mark.parametrize("bidirectional", [True, False])
    def test_custom_weight_chooses_minimum_cost_instead_of_shortest_geometry(self, bidirectional):
        start, via, end = (0, 0), (0, 0.01), (0.01, 0)
        roads = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"cost": cost},
             "geometry": {"type": "LineString", "coordinates": [a, b]}}
            for a, b, cost in [(start, end, 100), (start, via, 1), (via, end, 1)]
        ]}

        result = shortest_route(roads, start, end, weight_field="cost", bidirectional=bidirectional)

        assert "error" not in result
        assert [tuple(p) for p in result["path"]["geometry"]["coordinates"]] == [start, via, end]







# ============================================================
# 测试 service_area
# ============================================================

class TestServiceArea:
    def test_service_area_basic(self):
        """从 E 出发，500m 服务区应覆盖所有相邻节点"""
        result = service_area(GRID_GEOJSON, _NODES["E"], breaks=[500])
        assert "error" not in result
        assert len(result["polygons"]["features"]) == 1
        assert result["areas"][0]["break"] == 500
        assert result["areas"][0]["area_km2"] > 0
        properties = result["polygons"]["features"][0]["properties"]
        assert properties["approximate"] is True
        assert properties["boundary_method"] == "reachable_node_convex_hull"




# ============================================================
# 测试 closest_facilities
# ============================================================

class TestClosestFacilities:
    def test_closest_facilities_basic(self):
        """事件在 A，设施在 B, G, I，最近的是 B"""
        result = closest_facilities(
            GRID_GEOJSON, _NODES["A"],
            [_NODES["B"], _NODES["G"], _NODES["I"]],
            n=3,
        )
        assert "error" not in result
        assert len(result["paths"]) == 3
        assert len(result["summary"]) == 3
        # 最近的是 B（相邻，水平边约 426m）
        assert result["summary"][0]["facility_idx"] == 0
        assert 400 < result["summary"][0]["distance_m"] < 600

    def test_reports_facilities_outside_snap_range_and_without_a_route(self):
        roads = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {},
             "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.01, 0]]}},
            {"type": "Feature", "properties": {},
             "geometry": {"type": "LineString", "coordinates": [[1, 1], [1.01, 1]]}},
        ]}

        result = closest_facilities(roads, (0, 0), [(0.01, 0), (1, 1), (5, 5)], n=3)

        assert result["summary"][0]["facility_idx"] == 0
        assert result["unreachable_facility_indices"] == [1]
        assert result["unsnapped_facility_indices"] == [2]




# ============================================================
# 测试 haversine 工具函数
# ============================================================

class TestHaversine:
    def test_known_distance(self):
        """北京到上海约 1068km"""
        beijing = (116.4074, 39.9042)
        shanghai = (121.4737, 31.2304)
        d = _haversine(beijing, shanghai)
        assert abs(d - 1068000) < 50000  # 50km 容忍


