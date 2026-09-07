"""
DataV 行政区划边界获取工具
从阿里云 DataV（国内可访问）获取省/市/区边界，转 WGS-84
"""
import json, os, requests
from backend.services.geo_coords import gcj02_to_wgs84

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

def _load_city_adcodes():
    """
    从所有省份的 DataV GeoJSON 中提取城市/区县 adcode，构建名称→adcode 映射。
    结果缓存到本地文件，仅首次需要遍历所有省份+地级市。
    """
    cache_path = os.path.join(_CACHE_DIR, "_city_adcodes.json")
    # 尝试读缓存
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    # 从省份字典的 adcode，逐个拉取省份 GeoJSON 提取城市
    city_map = {}
    city_adcodes = []  # 保存市级 adcode，用于后续提取区级
    for prov_name, prov_adcode in _ADCODES.items():
        try:
            url = f"https://geo.datav.aliyun.com/areas_v3/bound/{prov_adcode}_full.json"
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for feat in data.get('features', []):
                    p = feat.get('properties', {})
                    name = p.get('name', '')
                    adcode = p.get('adcode', 0)
                    level = p.get('level', '')
                    if name and adcode:
                        city_map[name] = adcode
                        # 也存去掉后缀的版本（如 "广州" 来自 "广州市"）
                        for sfx in ['市', '区', '县', '自治州']:
                            if name.endswith(sfx):
                                city_map[name[:-len(sfx)]] = adcode
                        if level == 'city' or name.endswith('市'):
                            city_adcodes.append((name, adcode))
        except Exception:
            continue

    # 从每个地级市 GeoJSON 中提取区级 adcode
    for city_name, city_adcode in city_adcodes:
        try:
            url = f"https://geo.datav.aliyun.com/areas_v3/bound/{city_adcode}_full.json"
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for feat in data.get('features', []):
                    p = feat.get('properties', {})
                    name = p.get('name', '')
                    adcode = p.get('adcode', 0)
                    if name and adcode and name not in city_map:
                        city_map[name] = adcode
                        for sfx in ['区', '县', '市']:
                            if name.endswith(sfx):
                                bare = name[:-len(sfx)]
                                if bare not in city_map:
                                    city_map[bare] = adcode
        except Exception:
            continue

    # 写缓存
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(city_map, f, ensure_ascii=False)
    except Exception:
        pass

    return city_map


def _find_adcode(name):
    """
    根据名称查找 adcode，支持省/市/区三级。
    优先用本地省份字典，找不到则从 DataV 省份 GeoJSON 中提取城市 adcode 并缓存。
    """
    # 先在省份字典里查
    if name in _ADCODES:
        return _ADCODES[name]
    for suffix in ['省', '市', '区', '县', '自治州', '自治区', '特别行政区']:
        if name.endswith(suffix):
            bare = name[:-len(suffix)]
            for k, v in _ADCODES.items():
                if bare in k:
                    return v
    # 不是省份，从城市 adcode 字典查
    city_map = _load_city_adcodes()
    if city_map:
        if name in city_map:
            return city_map[name]
        for sfx in ['市', '区', '县']:
            if name.endswith(sfx) and name[:-len(sfx)] in city_map:
                return city_map[name[:-len(sfx)]]
            if name + sfx in city_map:
                return city_map[name + sfx]
    return 0


def _convert(coords):
    """递归将 GCJ-02 坐标转为 WGS-84"""
    if not coords: return coords
    if isinstance(coords[0], (int, float)):
        return list(gcj02_to_wgs84(coords[0], coords[1]))
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
    target_code = None
    if resp.status_code != 200:
        code = _find_adcode(name)
        if code:
            target_code = code
            resp = requests.get(f"https://geo.datav.aliyun.com/areas_v3/bound/{code}_full.json", timeout=15)

    # 区级 adcode 直接请求会 404，需从市级 GeoJSON 中提取
    if resp.status_code != 200 and target_code and isinstance(target_code, (int, str)):
        code_str = str(target_code)
        if len(code_str) == 6 and not code_str.endswith('00'):
            # 推断市级 adcode（前四位 + 00）
            city_code = code_str[:4] + '00'
            city_resp = requests.get(f"https://geo.datav.aliyun.com/areas_v3/bound/{city_code}_full.json", timeout=15)
            if city_resp.status_code == 200:
                city_data = city_resp.json()
                # 从市级 GeoJSON 中过滤出目标区级
                target_features = []
                for feat in city_data.get('features', []):
                    props = feat.get('properties', {})
                    feat_code = str(props.get('adcode', ''))
                    feat_name = props.get('name', '')
                    if feat_code == code_str or feat_name == name or feat_name == name.rstrip('区县市'):
                        target_features.append(feat)
                if target_features:
                    data = {'type': 'FeatureCollection', 'features': target_features}
                    # 转换坐标
                    if data.get("features"):
                        for feat in data["features"]:
                            if feat.get("geometry", {}).get("coordinates"):
                                feat["geometry"]["coordinates"] = _convert(feat["geometry"]["coordinates"])
                    # 写缓存
                    try:
                        with open(cache_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False)
                    except Exception:
                        pass
                    return data

    if resp.status_code != 200:
        return None

    data = resp.json()

    # DataV areas_v3 返回的是 GCJ-02 坐标，需转换为 WGS-84
    if data.get("features"):
        for feat in data["features"]:
            if feat.get("geometry", {}).get("coordinates"):
                feat["geometry"]["coordinates"] = _convert(feat["geometry"]["coordinates"])

    # 写缓存（已转 WGS-84）
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass

    return data
