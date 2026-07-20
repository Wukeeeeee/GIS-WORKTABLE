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

    def test_build_graph_has_edges(self):
        g = build_graph_from_geojson(GRID_GEOJSON)
        assert g.number_of_edges() == 24  # 12 边 × 2 方向

    def test_build_graph_empty(self):
        g = build_graph_from_geojson({"type": "FeatureCollection", "features": []})
        assert g.number_of_nodes() == 0

    def test_build_graph_edge_weight(self):
        g = build_graph_from_geojson(GRID_GEOJSON)
        a, b = _NODES["A"], _NODES["B"]
        d = g[a][b]["distance"]
        assert 400 < d < 600  # 水平边约 426m
        assert g[a][b]["weight"] == d


# ============================================================
# 测试 find_nearest_node
# ============================================================

class TestFindNearestNode:
    def test_find_nearest_exact(self):
        g = build_graph_from_geojson(GRID_GEOJSON)
        node = find_nearest_node(g, _NODES["E"], max_dist=1000)
        assert node == _NODES["E"]

    def test_find_nearest_nearby(self):
        g = build_graph_from_geojson(GRID_GEOJSON)
        # 靠近 A 的点
        nearby = (116.3005, 39.9002)
        node = find_nearest_node(g, nearby, max_dist=1000)
        assert node == _NODES["A"]

    def test_find_nearest_too_far(self):
        g = build_graph_from_geojson(GRID_GEOJSON)
        far = (116.0, 30.0)
        node = find_nearest_node(g, far, max_dist=500)
        assert node is None

    def test_find_nearest_empty_graph(self):
        g = build_graph_from_geojson({"type": "FeatureCollection", "features": []})
        node = find_nearest_node(g, (0, 0))
        assert node is None


# ============================================================
# 测试 snap_to_network
# ============================================================

class TestSnapToNetwork:
    def test_snap_exact(self):
        result = snap_to_network(GRID_GEOJSON, _NODES["B"])
        assert result["found"] is True
        assert result["snapped"] == list(_NODES["B"])

    def test_snap_nearby(self):
        nearby = (116.3045, 39.8995)
        result = snap_to_network(GRID_GEOJSON, nearby)
        assert result["found"] is True
        # 应吸附到最近的节点
        assert result["distance_m"] < 100

    def test_snap_too_far_returns_closest(self):
        far = (116.0, 30.0)
        result = snap_to_network(GRID_GEOJSON, far)
        assert result["found"] is False
        assert result["snapped"] is not None
        assert result["distance_m"] > 1000


# ============================================================
# 测试 shortest_route
# ============================================================

class TestShortestRoute:
    def test_route_adjacent(self):
        result = shortest_route(GRID_GEOJSON, _NODES["A"], _NODES["B"])
        assert "error" not in result
        assert 400 < result["distance_m"] < 600  # 水平边约 426m
        assert result["node_count"] == 2

    def test_route_diagonal(self):
        """A → I 最短路径（4段边，约 1965m）"""
        result = shortest_route(GRID_GEOJSON, _NODES["A"], _NODES["I"])
        assert "error" not in result
        assert result["node_count"] == 5
        # 网格对角线距离在 1900-2000m 之间（2横+2纵）
        assert 1900 < result["distance_m"] < 2000

    def test_route_far_from_network(self):
        far_point = (116.0, 30.0)
        result = shortest_route(GRID_GEOJSON, far_point, _NODES["B"])
        assert "error" in result

    def test_route_with_waypoint(self):
        """A → D → I: A先到D再到I"""
        result = shortest_route(GRID_GEOJSON, _NODES["A"], _NODES["I"], waypoints=[_NODES["D"]])
        assert "error" not in result
        # A→D (1段) + D→I (D→G→H→I 3段) = 4 段边
        assert result["node_count"] == 5
        assert result["segments"][0]["from"] == list(_NODES["A"])
        assert result["segments"][1]["to"] == list(_NODES["I"])
        assert len(result["segments"]) == 2

    def test_route_with_multiple_waypoints(self):
        """A → D → H → C"""
        result = shortest_route(GRID_GEOJSON, _NODES["A"], _NODES["C"],
                                waypoints=[_NODES["D"], _NODES["H"]])
        assert "error" not in result
        assert len(result["segments"]) == 3  # A→D, D→H, H→C

    def test_route_empty_graph(self):
        result = shortest_route({"type": "FeatureCollection", "features": []}, (0, 0), (1, 1))
        assert "error" in result


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

    def test_service_area_multi_breaks(self):
        """300m 够不到相邻节点（~555m），只有 800m 和 1500m 能出多边形"""
        result = service_area(GRID_GEOJSON, _NODES["E"], breaks=[300, 800, 1500])
        assert "error" not in result
        assert len(result["polygons"]["features"]) == 2
        assert len(result["areas"]) == 2
        assert result["areas"][0]["break"] == 800

    def test_service_area_far_point(self):
        result = service_area(GRID_GEOJSON, (116.0, 30.0), breaks=[500])
        assert "error" in result


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

    def test_closest_facilities_limit_n(self):
        result = closest_facilities(
            GRID_GEOJSON, _NODES["A"],
            [_NODES["B"], _NODES["G"], _NODES["I"]],
            n=2,
        )
        assert "error" not in result
        assert len(result["summary"]) == 2

    def test_closest_facilities_no_path(self):
        """孤立点应返回 error"""
        result = closest_facilities(
            GRID_GEOJSON, _NODES["A"],
            [(116.0, 30.0)],
            n=1,
        )
        assert "error" in result


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

    def test_same_point(self):
        assert _haversine((0, 0), (0, 0)) == 0

    def test_symmetric(self):
        a, b = (10, 20), (30, 40)
        assert abs(_haversine(a, b) - _haversine(b, a)) < 0.001
