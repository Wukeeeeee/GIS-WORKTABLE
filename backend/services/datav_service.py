"""
DataV 行政区划边界获取工具
从阿里云 DataV（国内可访问）获取省/市/区边界，转 WGS-84
"""
import hashlib
import json
import os
import requests
from urllib.parse import quote
from backend.services.geo_coords import gcj02_to_wgs84

# 缓存目录
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "cache", "aoi")
# 缓存版本号：坐标转换算法修复后 +1，旧版本缓存自动失效
_CACHE_VERSION = 2
_HEADERS = {"User-Agent": "Mozilla/5.0"}

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
            resp = requests.get(url, timeout=15, headers=_HEADERS)
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
            resp = requests.get(url, timeout=15, headers=_HEADERS)
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


# 常见多地重名区县字典（全国重名区县消歧）
_AMBIGUOUS_DISTRICTS = {
    "鼓楼区": [
        {"label": "江苏省南京市鼓楼区", "city": "南京市", "province": "江苏省", "adcode": 320106, "desc": "江苏省省会核心区"},
        {"label": "福建省福州市鼓楼区", "city": "福州市", "province": "福建省", "adcode": 350102, "desc": "福建省省会核心区，三坊七巷所在地"},
        {"label": "江苏省徐州市鼓楼区", "city": "徐州市", "province": "江苏省", "adcode": 320302, "desc": "徐州市主城区"},
        {"label": "河南省开封市鼓楼区", "city": "开封市", "province": "河南省", "adcode": 410204, "desc": "开封市古城区，大相国寺所在地"},
    ],
    "朝阳区": [
        {"label": "北京市朝阳区", "city": "北京市", "province": "北京市", "adcode": 110105, "desc": "北京市中心城区，CBD / 奥运公园所在地"},
        {"label": "吉林省长春市朝阳区", "city": "长春市", "province": "吉林省", "adcode": 220104, "desc": "长春市核心主城区，南湖公园所在地"},
    ],
    "和平区": [
        {"label": "天津市和平区", "city": "天津市", "province": "天津市", "adcode": 120101, "desc": "天津市核心中心区，五大道所在地"},
        {"label": "辽宁省沈阳市和平区", "city": "沈阳市", "province": "辽宁省", "adcode": 210102, "desc": "沈阳市主城区，太原街商圈所在地"},
    ],
    "普陀区": [
        {"label": "上海市普陀区", "city": "上海市", "province": "上海市", "adcode": 310107, "desc": "上海市中心城区，苏州河沿岸"},
        {"label": "浙江省舟山市普陀区", "city": "舟山市", "province": "浙江省", "adcode": 330903, "desc": "舟山市辖区，普陀山风景名胜区所在地"},
    ],
    "西湖区": [
        {"label": "浙江省杭州市西湖区", "city": "杭州市", "province": "浙江省", "adcode": 330106, "desc": "杭州市主城区，西湖风景名胜区所在地"},
        {"label": "江西省南昌市西湖区", "city": "南昌市", "province": "江西省", "adcode": 360103, "desc": "南昌市中心城区，滕王阁所在地"},
    ],
    "白云区": [
        {"label": "广东省广州市白云区", "city": "广州市", "province": "广东省", "adcode": 440111, "desc": "广州市辖区，白云山 / 白云机场所在地"},
        {"label": "贵州省贵阳市白云区", "city": "贵阳市", "province": "贵州省", "adcode": 520113, "desc": "贵阳市辖区，铝工业与大数据发展区"},
    ],
    "城关区": [
        {"label": "甘肃省兰州市城关区", "city": "兰州市", "province": "甘肃省", "adcode": 620102, "desc": "兰州市主城区，甘肃省委省政府所在地"},
        {"label": "西藏自治区拉萨市城关区", "city": "拉萨市", "province": "西藏自治区", "adcode": 540102, "desc": "拉萨市核心区，布达拉宫 / 大昭寺所在地"},
    ],
    "龙华区": [
        {"label": "广东省深圳市龙华区", "city": "深圳市", "province": "广东省", "adcode": 440309, "desc": "深圳市辖区，深圳北站枢纽所在地"},
        {"label": "海南省海口市龙华区", "city": "海口市", "province": "海南省", "adcode": 460106, "desc": "海口市核心城区，骑楼老街所在地"},
    ],
    "宝山区": [
        {"label": "上海市宝山区", "city": "上海市", "province": "上海市", "adcode": 310113, "desc": "上海市辖区，吴淞口国际邮轮港所在地"},
        {"label": "黑龙江省双鸭山市宝山区", "city": "双鸭山市", "province": "黑龙江省", "adcode": 230506, "desc": "双鸭山市辖区"},
    ],
    "新华区": [
        {"label": "河北省石家庄市新华区", "city": "石家庄市", "province": "河北省", "adcode": 130105, "desc": "石家庄市主城区"},
        {"label": "河北省沧州市新华区", "city": "沧州市", "province": "河北省", "adcode": 130903, "desc": "沧州市主城区"},
        {"label": "河南省平顶山市新华区", "city": "平顶山市", "province": "河南省", "adcode": 410402, "desc": "平顶山市核心区"},
    ],
    "桥西区": [
        {"label": "河北省石家庄市桥西区", "city": "石家庄市", "province": "河北省", "adcode": 130104, "desc": "石家庄市主城区"},
        {"label": "河北省张家口市桥西区", "city": "张家口市", "province": "河北省", "adcode": 130703, "desc": "张家口市主城区"},
    ],
}


def get_ambiguous_candidates(name: str) -> list[dict] | None:
    """检查输入地名是否存在多地重名，并按已提供的省/市限定候选。"""
    clean_name = (name or "").strip()
    if not clean_name:
        return None
    target_key = None
    for k in _AMBIGUOUS_DISTRICTS:
        if clean_name.endswith(k) or clean_name.endswith(k.rstrip("区")):
            target_key = k
            break
    if not target_key:
        return None
    candidates = _AMBIGUOUS_DISTRICTS[target_key]
    city_matches = [
        cand for cand in candidates
        if cand["city"] in clean_name or cand["city"].rstrip("市") in clean_name
    ]
    if city_matches:
        return city_matches if len(city_matches) > 1 else None

    province_matches = [
        cand for cand in candidates
        if cand["province"] in clean_name
        or cand["province"].rstrip("省").rstrip("市").rstrip("自治区") in clean_name
    ]
    if province_matches:
        return province_matches if len(province_matches) > 1 else None
    return candidates


def _find_adcode(name: str) -> int:
    """
    根据名称查找 adcode，支持省/市/区三级。
    优先精确匹配消歧全称（如 江苏省南京市鼓楼区），其次省份字典，最后城市/区县字典。
    """
    clean_name = (name or "").strip()
    if not clean_name:
        return 0

    # 1. 优先按城市/省份限定同名区县；无法唯一确定时不猜第一个。
    for base_district, candidates in _AMBIGUOUS_DISTRICTS.items():
        if not (clean_name.endswith(base_district) or clean_name.endswith(base_district.rstrip("区"))):
            continue
        city_matches = [
            cand for cand in candidates
            if cand["city"] in clean_name or cand["city"].rstrip("市") in clean_name
        ]
        if city_matches:
            return city_matches[0]["adcode"] if len(city_matches) == 1 else 0
        province_matches = [
            cand for cand in candidates
            if cand["province"] in clean_name
            or cand["province"].rstrip("省").rstrip("市").rstrip("自治区") in clean_name
        ]
        if province_matches:
            return province_matches[0]["adcode"] if len(province_matches) == 1 else 0
        return 0

    # 2. 先在省份字典里查
    if clean_name in _ADCODES:
        return _ADCODES[clean_name]
    for suffix in ['省', '市', '区', '县', '自治州', '自治区', '特别行政区']:
        if clean_name.endswith(suffix):
            bare = clean_name[:-len(suffix)]
            for k, v in _ADCODES.items():
                if bare in k:
                    return v

    # 3. 不是省份，从城市 adcode 字典查
    city_map = _load_city_adcodes()
    if city_map:
        if clean_name in city_map:
            return city_map[clean_name]
        for sfx in ['市', '区', '县']:
            if clean_name.endswith(sfx) and clean_name[:-len(sfx)] in city_map:
                return city_map[clean_name[:-len(sfx)]]
            if clean_name + sfx in city_map:
                return city_map[clean_name + sfx]
    return 0


def _convert(coords):
    """递归将 GCJ-02 坐标转为 WGS-84"""
    if not coords:
        return coords
    if isinstance(coords[0], (int, float)):
        return [*gcj02_to_wgs84(coords[0], coords[1]), *coords[2:]]
    return [_convert(c) for c in coords]


def fetch_boundary_by_adcode(adcode: int | str) -> dict | None:
    """按 adcode 直接获取该行政区的「下一级全集」边界（下钻用）。

    返回 GeoJSON FeatureCollection（已转 WGS-84），每个 feature 的 properties
    含 adcode / name / level。例如 adcode=430000 返回湖南 14 个地级市。
    失败返回 None。缓存复用 fetch_boundary 的目录（键为 adcode 数字串）。
    """
    adcode = str(adcode).strip()
    if not adcode.isdigit() or len(adcode) != 6:
        return None
    os.makedirs(_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(_CACHE_DIR, f"datav_adcode_{adcode}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            if isinstance(cached, dict) and cached.get("_cache_version") == _CACHE_VERSION:
                cached.pop("_cache_version", None)
                return cached
        except Exception:
            pass
    try:
        resp = requests.get(
            f"https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json", timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data.get("features"):
            return None
        for feat in data["features"]:
            if feat.get("geometry", {}).get("coordinates"):
                feat["geometry"]["coordinates"] = _convert(feat["geometry"]["coordinates"])
        try:
            data["_cache_version"] = _CACHE_VERSION
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass
        data.pop("_cache_version", None)
        return data
    except Exception:
        return None


def fetch_boundary(name: str) -> dict | None:
    """
    从 DataV 获取行政区划边界，返回 GeoJSON（已转 WGS-84）
    支持省/市/区三级，例如：广东省、广州市、天河区
    """
    name = (name or "").strip()
    if not name:
        return None
    os.makedirs(_CACHE_DIR, exist_ok=True)
    cache_key = hashlib.sha256(name.encode("utf-8")).hexdigest()[:32]
    cache_path = os.path.join(_CACHE_DIR, f"datav_{cache_key}.json")

    # 检查缓存（校验版本：坐标转换算法升级后旧缓存自动失效，防止错误坐标永久命中）
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            if isinstance(cached, dict) and cached.get("_cache_version") == _CACHE_VERSION:
                cached.pop("_cache_version", None)
                return cached
        except Exception:
            pass

    # 先用名称直接请求
    url = f"https://geo.datav.aliyun.com/areas_v3/bound/{quote(name, safe='')}_full.json"
    resp = requests.get(url, timeout=15, headers=_HEADERS)

    # 失败则用 adcode
    target_code = None
    if resp.status_code != 200:
        code = _find_adcode(name)
        if code:
            target_code = code
            resp = requests.get(f"https://geo.datav.aliyun.com/areas_v3/bound/{code}_full.json", timeout=15, headers=_HEADERS)

    # 区级 adcode 直接请求会 404，需从市级 GeoJSON 中提取
    if resp.status_code != 200 and target_code and isinstance(target_code, (int, str)):
        code_str = str(target_code)
        if len(code_str) == 6 and not code_str.endswith('00'):
            # 推断市级 adcode（前四位 + 00）
            city_code = code_str[:4] + '00'
            city_resp = requests.get(f"https://geo.datav.aliyun.com/areas_v3/bound/{city_code}_full.json", timeout=15, headers=_HEADERS)
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
                    # 写缓存（打版本标记）
                    try:
                        data["_cache_version"] = _CACHE_VERSION
                        with open(cache_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False)
                    except Exception:
                        pass
                    data.pop("_cache_version", None)
                    return data

    if resp.status_code != 200:
        return None

    data = resp.json()

    # DataV areas_v3 返回的是 GCJ-02 坐标，需转换为 WGS-84
    if data.get("features"):
        for feat in data["features"]:
            if feat.get("geometry", {}).get("coordinates"):
                feat["geometry"]["coordinates"] = _convert(feat["geometry"]["coordinates"])

    # 写缓存（已转 WGS-84，打版本标记供读取侧校验）
    try:
        data["_cache_version"] = _CACHE_VERSION
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass
    data.pop("_cache_version", None)

    return data
