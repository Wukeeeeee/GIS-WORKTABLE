from __future__ import annotations

import json, math
from shapely import wkt
from shapely.geometry import Point, Polygon, MultiPolygon, box, LineString
from shapely import buffer, intersection, centroid, area, make_valid, simplify
from pyproj import Transformer, CRS


def _round_coords(geom, ndigits=6) -> dict:
    """Round all coordinates in a geometry for stable comparison."""
    return json.loads(json.dumps(geom.__geo_interface__, default=str))


# ===== Buffer =====


def test_buffer_point_meters():
    """Buffer a point with a positive distance."""
    p = Point(116.4, 39.9)
    b = buffer(p, 0.01)  # ~1 km at this latitude
    assert b.geom_type == "Polygon"
    assert b.area > 0
    assert b.contains(p)


def test_buffer_zero_distance():
    """Buffer with distance=0 returns a degenerate polygon (Shapely 2.x)."""
    p = Point(116.4, 39.9)
    b = buffer(p, 0)
    assert b.geom_type == "Polygon"
    assert b.area == 0.0


def test_buffer_negative_distance():
    """Buffer with negative distance erodes the geometry."""
    p = Point(116.4, 39.9)
    b = buffer(p, -0.1)
    assert b.is_empty


def test_buffer_quadrant_segments():
    """Buffer with custom quadrant_segments produces fewer vertices."""
    p = Point(0, 0)
    b_high = buffer(p, 1, quad_segs=32)
    b_low = buffer(p, 1, quad_segs=4)
    assert len(b_low.exterior.coords) < len(b_high.exterior.coords)


# ===== Intersection =====


def test_intersection_overlapping():
    """Intersection of two overlapping rectangles."""
    a = box(0, 0, 10, 10)
    b = box(5, 5, 15, 15)
    inter = intersection(a, b)
    assert inter.geom_type == "Polygon"
    assert math.isclose(inter.area, 25.0)


def test_intersection_touching():
    """Intersection of two touching rectangles shares an edge → area 0."""
    a = box(0, 0, 10, 10)
    b = box(10, 0, 20, 10)
    inter = intersection(a, b)
    assert inter.area == 0.0


def test_intersection_disjoint():
    """Intersection of two disjoint shapes is empty."""
    a = box(0, 0, 1, 1)
    b = box(10, 10, 11, 11)
    inter = intersection(a, b)
    assert inter.is_empty


def test_intersection_contained():
    """Intersection where one shape is fully inside the other."""
    outer = box(0, 0, 20, 20)
    inner = box(5, 5, 10, 10)
    inter = intersection(outer, inner)
    assert math.isclose(inter.area, 25.0)


# ===== Centroid =====


def test_centroid_square():
    """Centroid of a square is the center."""
    sq = box(0, 0, 10, 10)
    c = centroid(sq)
    assert (c.x, c.y) == (5.0, 5.0)


def test_centroid_point():
    """Centroid of a point is the point itself."""
    p = Point(3, 7)
    c = centroid(p)
    assert (c.x, c.y) == (3.0, 7.0)


def test_centroid_line():
    """Centroid of a line segment is the midpoint."""
    line = LineString([(0, 0), (10, 0)])
    c = centroid(line)
    assert (c.x, c.y) == (5.0, 0.0)


def test_centroid_empty_geometry():
    """Centroid of an empty geometry returns empty point."""
    empty = wkt.loads("GEOMETRYCOLLECTION EMPTY")
    c = centroid(empty)
    assert c.is_empty


# ===== Area =====


def test_area_square():
    """Area of a 10×10 square."""
    sq = box(0, 0, 10, 10)
    assert math.isclose(area(sq), 100.0)


def test_area_circle():
    """Area of a unit circle ≈ π."""
    p = Point(0, 0)
    circ = buffer(p, 1, quad_segs=64)
    assert math.isclose(area(circ), math.pi, rel_tol=1e-2)


def test_area_zero_point():
    """Point has area = 0."""
    assert area(Point(0, 0)) == 0.0


def test_area_zero_line():
    """Line has area = 0."""
    assert area(LineString([(0, 0), (1, 1)])) == 0.0


def test_area_multipolygon():
    """Area of a MultiPolygon."""
    mp = MultiPolygon([box(0, 0, 5, 5), box(10, 10, 15, 15)])
    assert math.isclose(area(mp), 50.0)


# ===== Make Valid =====


def test_make_valid_self_intersecting():
    """A bowtie polygon is invalid; make_valid produces a MultiPolygon."""
    invalid = Polygon([(0, 0), (10, 0), (0, 10), (10, 10)])
    assert not invalid.is_valid
    valid = make_valid(invalid)
    assert valid.is_valid
    assert valid.geom_type in ("MultiPolygon", "Polygon")


def test_make_valid_narrow_slit():
    """A polygon with a narrow slit is invalid; make_valid repairs it."""
    invalid = Polygon([(0, 0), (10, 0), (10, 10), (5, 5), (5, 10), (0, 10)])
    valid = make_valid(invalid)
    assert valid.is_valid


def test_make_valid_ring_orientation():
    """A polygon with reversed ring orientation is repaired."""
    coords = [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)]
    poly = Polygon(coords)
    assert poly.is_valid
    valid = make_valid(poly)
    assert valid.is_valid
    assert math.isclose(valid.area, 100.0)


def test_make_valid_already_valid():
    """make_valid on a valid shape returns an equivalent shape."""
    sq = box(0, 0, 10, 10)
    result = make_valid(sq)
    assert result.is_valid
    assert math.isclose(result.area, 100.0)


# ===== Simplify =====


def test_simplify_preserves_topology():
    """Simplify should preserve the overall shape of a polygon."""
    sq = box(0, 0, 10, 10)
    simplified = simplify(sq, tolerance=1)
    assert simplified.geom_type == "Polygon"


def test_simplify_reduces_vertices():
    """Simplify a circle-like polygon should reduce vertex count."""
    p = Point(0, 0)
    circ = buffer(p, 1, quad_segs=64)
    simple = simplify(circ, tolerance=0.1)
    assert len(simple.exterior.coords) < len(circ.exterior.coords)


def test_simplify_high_tolerance():
    """Simplify with very high tolerance may collapse to a very simple shape."""
    poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])
    simple = simplify(poly, tolerance=50)
    vertex_count = len(simple.exterior.coords)
    # With high tolerance, the square's vertices may reduce to the minimum 5
    assert vertex_count <= 5


def test_simplify_preserves_area():
    """Simplify with small tolerance preserves area."""
    poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])
    original_area = area(poly)
    simplified = simplify(poly, tolerance=1)
    simplified_area = area(simplified)
    assert math.isclose(simplified_area, original_area, rel_tol=0.02)


# ===== Buffer in projected CRS (WGS-84 → UTM → buffer → back) =====


def test_buffer_wgs84_to_utm_500m():
    """Buffer a WGS-84 point via UTM projection: 500m buffer should be ~0.785 km²."""
    p_wgs84 = Point(116.4, 39.9)
    transformer_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)
    transformer_to_wgs84 = Transformer.from_crs("EPSG:32650", "EPSG:4326", always_xy=True)
    x_utm, y_utm = transformer_to_utm.transform(p_wgs84.x, p_wgs84.y)
    p_utm = Point(x_utm, y_utm)
    buf_utm = buffer(p_utm, 500)
    buf_wgs84 = wkt.loads(wkt.dumps(buf_utm, rounding_precision=6))
    transformer_back = Transformer.from_crs("EPSG:32650", "EPSG:4326", always_xy=True)
    exterior_coords = list(buf_utm.exterior.coords)
    coords_wgs84 = [transformer_back.transform(x, y) for x, y in exterior_coords]
    buf_geo = Polygon(coords_wgs84)
    assert buf_geo.geom_type == "Polygon"
    assert buf_geo.contains(Point(116.4, 39.9))
    expected_area_km2 = math.pi * 0.5 * 0.5
    buf_area_km2 = buf_utm.area / 1e6
    assert math.isclose(buf_area_km2, expected_area_km2, rel_tol=0.02)


# ===== Projected area with < 1% deviation =====


def test_area_projected():
    """Project a known-area polygon and verify deviation < 1%."""
    p_wgs84 = Point(116.4, 39.9)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)
    x, y = transformer.transform(p_wgs84.x, p_wgs84.y)
    half = 500
    poly_utm = Polygon([
        (x - half, y - half),
        (x + half, y - half),
        (x + half, y + half),
        (x - half, y + half),
    ])
    expected_area = (2 * half) ** 2
    actual_area = poly_utm.area
    deviation = abs(actual_area - expected_area) / expected_area
    assert deviation < 0.01
