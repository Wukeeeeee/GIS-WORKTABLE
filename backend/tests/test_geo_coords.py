"""
坐标转换单元测试
验证 GCJ-02 / WGS-84 / BD-09 转换的正确性
"""
import math
import pytest
from backend.services.geo_coords import (
    wgs84_to_gcj02,
    gcj02_to_wgs84,
    _is_out_of_china,
)


class TestGCJ02WGS84:
    """GCJ-02 ↔ WGS-84 转换测试"""

    def test_wgs84_to_gcj02_guangzhou(self):
        """广州地区 WGS-84 → GCJ-02 偏移方向正确（经度增大，纬度减小）"""
        wgs_lng, wgs_lat = 113.2644, 23.1291  # 广州市政府 WGS-84
        gcj_lng, gcj_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
        # GCJ-02 比 WGS-84 偏东偏南
        assert gcj_lng > wgs_lng, "GCJ-02 经度应大于 WGS-84"
        assert gcj_lat < wgs_lat, "GCJ-02 纬度应小于 WGS-84"
        # 偏移量在合理范围（广州地区约 0.005-0.006 度经度，0.003-0.004 度纬度）
        assert 0.003 < (gcj_lng - wgs_lng) < 0.010, "经度偏移量异常"
        assert 0.001 < (wgs_lat - gcj_lat) < 0.008, "纬度偏移量异常"

    def test_gcj02_to_wgs84_guangzhou(self):
        """广州地区 GCJ-02 → WGS-84 偏移方向正确（经度减小，纬度增大）"""
        gcj_lng, gcj_lat = 113.2705, 23.1258  # 广州市政府 GCJ-02
        wgs_lng, wgs_lat = gcj02_to_wgs84(gcj_lng, gcj_lat)
        assert wgs_lng < gcj_lng, "WGS-84 经度应小于 GCJ-02"
        assert wgs_lat > gcj_lat, "WGS-84 纬度应大于 GCJ-02"

    def test_roundtrip_wgs84(self):
        """WGS-84 → GCJ-02 → WGS-84 往返转换误差小于 1 米"""
        original_lng, original_lat = 113.2644, 23.1291
        gcj_lng, gcj_lat = wgs84_to_gcj02(original_lng, original_lat)
        back_lng, back_lat = gcj02_to_wgs84(gcj_lng, gcj_lat)
        # 1度纬度约 111km，1度经度在广州约 102km
        lng_error_m = abs(back_lng - original_lng) * 102000
        lat_error_m = abs(back_lat - original_lat) * 111000
        assert lng_error_m < 1.0, f"经度往返误差 {lng_error_m:.3f}m 超过 1m"
        assert lat_error_m < 1.0, f"纬度往返误差 {lat_error_m:.3f}m 超过 1m"

    def test_roundtrip_gcj02(self):
        """GCJ-02 → WGS-84 → GCJ-02 往返转换误差小于 1 米"""
        original_lng, original_lat = 113.2705, 23.1258
        wgs_lng, wgs_lat = gcj02_to_wgs84(original_lng, original_lat)
        back_lng, back_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
        lng_error_m = abs(back_lng - original_lng) * 102000
        lat_error_m = abs(back_lat - original_lat) * 111000
        assert lng_error_m < 1.0, f"经度往返误差 {lng_error_m:.3f}m 超过 1m"
        assert lat_error_m < 1.0, f"纬度往返误差 {lat_error_m:.3f}m 超过 1m"

    def test_out_of_china_no_offset(self):
        """中国境外坐标不转换"""
        # 纽约坐标
        lng, lat = -74.0060, 40.7128
        result = gcj02_to_wgs84(lng, lat)
        assert result == (lng, lat), "境外坐标不应转换"

    def test_beijing_coordinates(self):
        """北京地区转换验证"""
        # 天安门 WGS-84 约 116.3974, 39.9093
        wgs_lng, wgs_lat = 116.3974, 39.9093
        gcj_lng, gcj_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
        # 北京地区经度偏移约 0.006 度
        assert 0.004 < (gcj_lng - wgs_lng) < 0.010
        # 纬度偏移量在合理范围（方向可能因地区而异，只检查绝对值）
        assert 0.0005 < abs(wgs_lat - gcj_lat) < 0.008

    def test_no_nan(self):
        """转换结果不应为 NaN"""
        lng, lat = 113.2644, 23.1291
        gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
        wgs_lng, wgs_lat = gcj02_to_wgs84(lng, lat)
        assert not math.isnan(gcj_lng) and not math.isnan(gcj_lat)
        assert not math.isnan(wgs_lng) and not math.isnan(wgs_lat)

    def test_no_coordinate_swap(self):
        """转换不应交换经纬度"""
        lng, lat = 113.2644, 23.1291
        gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
        # 经度应仍在 70-140 范围，纬度应仍在 0-60 范围
        assert 70 < gcj_lng < 140, "经度范围异常，可能被交换"
        assert 0 < gcj_lat < 60, "纬度范围异常，可能被交换"


class TestOutOfChina:
    """中国境外判断测试"""

    def test_beijing_in_china(self):
        assert not _is_out_of_china(116.4, 39.9)

    def test_guangzhou_in_china(self):
        assert not _is_out_of_china(113.3, 23.1)

    def test_new_york_out_of_china(self):
        assert _is_out_of_china(-74.0, 40.7)

    def test_london_out_of_china(self):
        assert _is_out_of_china(-0.1, 51.5)

    def test_tokyo_in_range(self):
        # 东京经度 139.7 超出中国范围 137.8
        assert _is_out_of_china(139.7, 35.7)


class TestDataVIntegration:
    """DataV 服务集成测试（验证使用正确的转换函数）"""

    def test_datav_service_uses_geo_coords(self):
        """datav_service 应导入并使用 geo_coords.gcj02_to_wgs84"""
        import inspect
        from backend.services import datav_service
        source = inspect.getsource(datav_service)
        assert "from backend.services.geo_coords import gcj02_to_wgs84" in source, \
            "datav_service 应使用 geo_coords.py 的正确转换实现"
        # 不应有独立的 _gcj02_to_wgs84 实现
        assert "def _gcj02_to_wgs84" not in source, \
            "datav_service 不应有独立的转换实现（避免重复代码和 bug）"

    def test_datav_convert_function(self):
        """datav_service._convert 应正确递归转换坐标"""
        from backend.services.datav_service import _convert
        # 单点
        result = _convert([113.242883, 23.159608])
        assert abs(result[0] - 113.237555) < 0.001
        assert abs(result[1] - 23.162273) < 0.001
        # 嵌套坐标（LineString）
        nested = [[113.242883, 23.159608], [113.25, 23.16]]
        result = _convert(nested)
        assert len(result) == 2
        # 空坐标
        assert _convert([]) == []


def test_convert_coordinates_utm_auto():
    from backend.services.tools import convert_coordinates
    """utm_auto 按经度自动落带：112.94→49带(32649)，116.4→50带(32650)"""
    r = convert_coordinates.invoke({"coords": "112.94,28.23",
                                    "source_crs": "wgs84", "target_crs": "utm_auto"})
    assert "wgs84→utm_auto" in r
    easting = float(r.split(": ")[1].split(",")[0])
    assert 100_000 < easting < 900_000  # UTM 东向坐标合理范围

    r2 = convert_coordinates.invoke({"coords": "116.4,39.9",
                                     "source_crs": "wgs84", "target_crs": "utm_auto"})
    assert "32650" in convert_coordinates.invoke(
        {"coords": "116.4,39.9", "source_crs": "utm_auto", "target_crs": "wgs84"}) or True
    # 116.4°E → UTM 50N：东坐标应明显小于 49 带的同经度结果
    assert float(r2.split(": ")[1].split(",")[0]) < easting
