"""
GIS WorkTable — 坐标转换工具（GCJ-02 / WGS-84 / BD-09 互转）

集中管理所有坐标系转换逻辑，避免多个服务文件重复实现。
"""

import math


# ============================================================
# 辅助函数
# ============================================================

def _transform_lat(lng: float, lat: float) -> float:
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * math.pi) + 40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320.0 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * math.pi) + 40.0 * math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 * math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def _is_out_of_china(lng: float, lat: float) -> bool:
    """粗略判断坐标是否在中国境外"""
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


# ============================================================
# GCJ-02 ↔ WGS-84（高德火星 → 全球标准）
# ============================================================

def _wgs84_to_gcj02(lng: float, lat: float) -> tuple:
    """WGS-84 → GCJ-02（内部用）"""
    a = 6378245.0
    ee = 0.00669342162296594323
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lng + dlng, lat + dlat


def gcj02_to_wgs84(lng: float, lat: float) -> tuple:
    """GCJ-02 → WGS-84，迭代法精度 0.1m"""
    if _is_out_of_china(lng, lat):
        return lng, lat
    wgs_lng, wgs_lat = lng, lat
    for _ in range(5):
        calc_gcj = _wgs84_to_gcj02(wgs_lng, wgs_lat)
        wgs_lng -= calc_gcj[0] - lng
        wgs_lat -= calc_gcj[1] - lat
    return wgs_lng, wgs_lat


# ============================================================
# BD-09 ↔ GCJ-02 ↔ WGS-84（百度墨卡托 → 火星 → 全球标准）
# ============================================================

def bd09mc_to_wgs84(points: list) -> list:
    """百度墨卡托坐标 → WGS-84 坐标列表
    需要 transbigdata 库支持"""
    try:
        import transbigdata
    except ImportError:
        raise ImportError("BD-09 转换需要 transbigdata 库：pip install transbigdata")

    result = []
    for x, y in points:
        bd09_lon, bd09_lat = transbigdata.bd09mctobd09(x, y)
        gcj02_lon, gcj02_lat = transbigdata.bd09togcj02(bd09_lon, bd09_lat)
        wgs84_lon, wgs84_lat = transbigdata.gcj02towgs84(gcj02_lon, gcj02_lat)
        result.append((round(wgs84_lon, 6), round(wgs84_lat, 6)))
    return result
