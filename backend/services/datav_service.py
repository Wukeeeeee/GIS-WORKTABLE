"""
DataV 行政区划边界获取工具
从阿里云 DataV（国内可访问）获取省/市/区边界，转 WGS-84
"""
import json, os, math, requests

# 缓存目录
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "cache", "aoi")

# 省级 adcode 字典
_ADCODES = {
    '北京市': 110000, '天津市': 120000, '河北省': 130000, '山西省': 140000,
    '内蒙古自治区': 150000, '辽宁省': 210000, '吉林省': 220000, '黑龙江省': 230000,
    '上海市': 310000, '江苏省': 320000, '浙江省': 330000, '安徽省': 340000,
    '福建省': 350000, '江西省': 360000, '山东省': 370000, '河南省': 410000,
    '湖北省': 420000, '湖南省': 430000, '广东省': 440000, '广西壮族自治区': 450000,
    '海南省': 460000, '重庆市': 500000, '四川省': 510000, '贵州省': 520000,
    '云南省': 530000, '西藏自治区': 540000, '陕西省': 610000, '甘肃省': 620000,
    '青海省': 630000, '宁夏回族自治区': 640000, '新疆维吾尔自治区': 650000,
    '台湾省': 710000, '香港特别行政区': 810000, '澳门特别行政区': 820000,
}

def _find_adcode(name):
    """根据名称找 adcode"""
    if name in _ADCODES:
        return _ADCODES[name]
    # 去掉后缀
    for suffix in ['省', '市', '区', '县', '自治州', '自治区', '特别行政区']:
        if name.endswith(suffix):
            bare = name[:-len(suffix)]
            for k, v in _ADCODES.items():
                if bare in k:
                    return v
    return 0


# GCJ-02 → WGS-84
def _transform_lat(lng, lat):
    ret = -100.0 + 2.0*lng + 3.0*lat + 0.2*lat*lat + 0.1*lng*lat + 0.2*math.sqrt(abs(lng))
    ret += (20.0*math.sin(6.0*lng*math.pi) + 20.0*math.sin(2.0*lng*math.pi)) * 2.0/3.0
    ret += (20.0*math.sin(lat*math.pi) + 40.0*math.sin(lat/3.0*math.pi)) * 2.0/3.0
    ret += (160.0*math.sin(lat/12.0*math.pi) + 320.0*math.sin(lat*math.pi/30.0)) * 2.0/3.0
    return ret

def _transform_lng(lng, lat):
    ret = 300.0 + lng + 2.0*lat + 0.1*lng*lng + 0.1*lng*lat + 0.1*math.sqrt(abs(lng))
    ret += (20.0*math.sin(6.0*lng*math.pi) + 20.0*math.sin(2.0*lng*math.pi)) * 2.0/3.0
    ret += (20.0*math.sin(lng*math.pi) + 40.0*math.sin(lng/3.0*math.pi)) * 2.0/3.0
    ret += (150.0*math.sin(lng/12.0*math.pi) + 320.0*math.sin(lng/30.0*math.pi)) * 2.0/3.0
    return ret

def _gcj02_to_wgs84(lng, lat):
    if not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271):
        return lng, lat
    a, ee = 6378245.0, 0.00669342162296594323
    wl, wla = lng, lat
    for _ in range(5):
        dlat = _transform_lat(wl - 105.0, wla - 35.0)
        dlng = _transform_lng(wl - 105.0, wla - 35.0)
        radlat = wla / 180.0 * math.pi
        magic = math.sin(radlat)
        magic = 1 - ee * magic * magic
        sqrtmagic = math.sqrt(magic)
        dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
        dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
        wl -= dlng; wla -= dlat
    return round(wl, 6), round(wla, 6)

def _convert(coords):
    if not coords: return coords
    if isinstance(coords[0], (int, float)):
        return list(_gcj02_to_wgs84(coords[0], coords[1]))
    return [_convert(c) for c in coords]


def fetch_boundary(name: str) -> dict:
    """
    从 DataV 获取行政区划边界，返回 GeoJSON（已转 WGS-84）
    支持省/市/区三级，例如：广东省、广州市、天河区
    """
    os.makedirs(_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(_CACHE_DIR, f"datav_{name}.json")

    # 检查缓存
    if os.path.exists(cache_path):
        with open(cache_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    # 先用名称直接请求
    url = f"https://geo.datav.aliyun.com/areas_v3/bound/{name}_full.json"
    resp = requests.get(url, timeout=15)

    # 失败则用 adcode
    if resp.status_code != 200:
        code = _find_adcode(name)
        if code:
            resp = requests.get(f"https://geo.datav.aliyun.com/areas_v3/bound/{code}_full.json", timeout=15)

    if resp.status_code != 200:
        return None

    data = resp.json()

    # 转 WGS-84
    for feat in data.get('features', []):
        geom = feat.get('geometry', {})
        if geom.get('type') in ('Polygon', 'MultiPolygon'):
            geom['coordinates'] = _convert(geom['coordinates'])

    # 写缓存
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass

    return data
