# -*- coding: utf-8 -*-
"""地铁线路服务层：国内高德 + 国际 OSM Overpass 双数据源（均为公开接口，零 key）。"""
from __future__ import annotations

import re
import time

import requests

CN_CITY_CODES = {
    "北京": ("1100", "beijing"), "上海": ("3100", "shanghai"), "广州": ("4401", "guangzhou"),
    "深圳": ("4403", "shenzhen"), "长沙": ("4301", "changsha"), "武汉": ("4201", "wuhan"),
    "成都": ("5101", "chengdu"), "西安": ("6101", "xian"), "重庆": ("5001", "chongqing"),
    "南京": ("3201", "nanjing"), "杭州": ("3301", "hangzhou"), "苏州": ("3205", "suzhou"),
    "天津": ("1200", "tianjin"), "郑州": ("4101", "zhengzhou"), "昆明": ("5301", "kunming"),
    "大连": ("2102", "dalian"), "哈尔滨": ("2301", "haerbin"), "沈阳": ("2101", "shenyang"),
    "长春": ("2201", "changchun"), "合肥": ("3401", "hefei"), "宁波": ("3302", "ningbo"),
    "南昌": ("3601", "nanchang"), "福州": ("3501", "fuzhou"), "东莞": ("4419", "dongguan"),
    "佛山": ("4406", "foshan"), "无锡": ("3202", "wuxi"), "青岛": ("3702", "qingdao"),
    "石家庄": ("1301", "shijiazhuang"), "贵阳": ("5201", "guiyang"), "兰州": ("6201", "lanzhou"),
}
_CITY_ALIAS = {
    "北京市": "北京", "上海市": "上海", "广州市": "广州", "深圳市": "深圳", "长沙市": "长沙",
    "beijing": "北京", "shanghai": "上海", "guangzhou": "广州", "shenzhen": "深圳", "changsha": "长沙",
    "wuhan": "武汉", "chengdu": "成都", "xian": "西安", "nanjing": "南京", "hangzhou": "杭州",
}

INTL_CITY_BBOX = {
    "tokyo": (139.4, 35.3, 140.1, 36.0), "osaka": (135.2, 34.4, 135.8, 34.8),
    "seoul": (126.7, 37.3, 127.3, 37.8), "singapore": (103.6, 1.1, 104.2, 1.6),
    "london": (-0.35, 51.2, 0.15, 51.7), "paris": (2.1, 48.7, 2.7, 49.0),
    "berlin": (13.0, 52.3, 13.6, 52.7), "madrid": (-4.0, 40.2, -3.4, 40.6),
    "new york": (-74.3, 40.5, -73.6, 41.0), "moscow": (37.2, 55.5, 38.1, 56.0),
    "东京": (139.4, 35.3, 140.1, 36.0), "纽约": (-74.3, 40.5, -73.6, 41.0),
    "伦敦": (-0.35, 51.2, 0.15, 51.7), "巴黎": (2.1, 48.7, 2.7, 49.0),
    "柏林": (13.0, 52.3, 13.6, 52.7), "首尔": (126.7, 37.3, 127.3, 37.8),
    "莫斯科": (37.2, 55.5, 38.1, 56.0), "马德里": (-4.0, 40.2, -3.4, 40.6),
    "新加坡": (103.6, 1.1, 104.2, 1.6), "大阪": (135.2, 34.4, 135.8, 34.8),
}

LINE_COLORS = {
    ("长沙", "1"): "#d02129", ("长沙", "2"): "#e63232", ("长沙", "3"): "#018089",
    ("长沙", "4"): "#3c8d44", ("长沙", "5"): "#00609e", ("长沙", "6"): "#7d5547",
    ("北京", "1"): "#c23a30", ("北京", "2"): "#006098", ("北京", "4"): "#008e9c",
    ("北京", "5"): "#a4343a", ("北京", "6"): "#d29700", ("北京", "10"): "#009bc0",
    ("上海", "1"): "#e4002b", ("上海", "2"): "#97d700", ("上海", "10"): "#c6afcf",
    ("广州", "1"): "#f3d03e", ("广州", "2"): "#00629b", ("广州", "3"): "#eca268",
    ("深圳", "1"): "#00b140", ("深圳", "2"): "#da6e00", ("深圳", "3"): "#00a0e9",
}

_UA = {"User-Agent": "GISWorkTable/1.0 (GIS analysis tool)"}
_cache = {}


def norm_city(city):
    c = (city or "").strip().lower()
    return _CITY_ALIAS.get(c, c)


_LINE_NOISE_RE = re.compile(r"(地铁|轻轨|号线|线路|轨道|线|line|metro|subway)", re.IGNORECASE)


def line_key(text) -> str:
    """线路匹配键：'广州地铁1号线'->'1'，'11号线'->'11'，'APM线'->'apm'。

    取数字编号（若有）作为键，这样「1号线」不会误命中「11号线」「21号线」。
    """
    s = str(text or "").strip().lower()
    if not s:
        return ""
    m = re.search(r"\d+", s)
    if m:
        return m.group(0)
    return _LINE_NOISE_RE.sub("", s)


def line_matches(line_name, line_filter) -> bool:
    """线路名是否匹配筛选条件：编号精确匹配优先，无编号（APM 线等）退化为包含匹配。"""
    f = str(line_filter or "").strip()
    if not f:
        return True
    n = str(line_name or "")
    if not n:
        return False
    fk, nk = line_key(f), line_key(n)
    if fk and nk:
        return fk == nk
    return f.lower() in n.lower()


def fetch_cn(city_norm):
    key = ("cn", city_norm)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    info = CN_CITY_CODES.get(city_norm)
    if not info:
        raise ValueError("暂不支持城市「%s」（国内已支持：%s）" % (city_norm, "、".join(sorted(CN_CITY_CODES))))
    code, py_ = info
    url = "https://map.amap.com/service/subway?_1700000000000&srhdata=%s_drw_%s.json" % (code, py_)
    # 高德偶发 TLS 断连（SSL: UNEXPECTED_EOF_WHILE_READING），重试 + urllib 直连兜底，
    # 避免一次网络抖动就让"地铁上地图"整条链路失败。
    d = None
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=15, headers=_UA)
            r.raise_for_status()
            d = r.json()
            break
        except Exception as e:
            last_err = e
        try:
            import urllib.request as _ur
            import json as _json
            with _ur.urlopen(_ur.Request(url, headers=_UA), timeout=15) as resp:
                d = _json.loads(resp.read().decode("utf-8"))
            break
        except Exception as e2:
            last_err = e2
            time.sleep(0.6 * (attempt + 1))
    if d is None:
        raise RuntimeError("高德地铁数据获取失败（网络波动，已重试 3 次）：%s" % str(last_err)[:200])
    if not isinstance(d, dict) or not d.get("l"):
        raise ValueError("城市「%s」暂无地铁数据" % city_norm)
    _cache[key] = (time.time(), d)
    return d




_OVERPASS_HOSTS = ["overpass-api.de", "overpass.kumi.systems", "overpass.osm.ch"]


def _overpass_post(q, timeout=120):
    """Overpass POST 多镜像轮询：requests SSL 偶发断连时用 urllib 直连兜底。"""
    import urllib.request as _ur
    data = ("data=" + _ur.quote(q)).encode()
    last_err = None
    for host in _OVERPASS_HOSTS:
        # 先 urllib 直连（不走代理Overpass 对代理 TLS 敏感）
        try:
            rq = _ur.Request("https://%s/api/interpreter" % host, data=data,
                             headers={"Content-Type": "application/x-www-form-urlencoded", **_UA})
            r = _ur.urlopen(rq, timeout=timeout)
            return r.json()
        except Exception as e:
            last_err = e
        # 再 requests+系统代理
        try:
            r = requests.post("https://%s/api/interpreter" % host, data={"data": q},
                              timeout=timeout, headers=_UA)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
    raise ValueError("Overpass 全镜像不可达: %s" % str(last_err)[:120])


def fetch_intl(city_norm):
    key = ("intl", city_norm)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    bbox = INTL_CITY_BBOX.get(city_norm)
    if not bbox:
        raise ValueError("暂不支持国际城市「%s」（可用：%s）" % (city_norm, "、".join(sorted(INTL_CITY_BBOX))))
    q = '[out:json][timeout:60];(relation["route"="subway"](%f,%f,%f,%f););out tags 60;' % bbox
    d = _overpass_post(q)
    rels = [e for e in d.get("elements", []) if e.get("type") == "relation"]
    if not rels:
        raise ValueError("城市「%s」在 OSM 暂无地铁路线数据" % city_norm)
    _cache[key] = (time.time(), rels)
    return rels


# ============================================================
# 图层构建（国内 GCJWGS 逆变换；国际 OSM 直接 WGS84）
# ============================================================

def cn_line_to_features(line_obj, city_norm):
    """高德线路 dict -> (line_feature, station_features, color)"""
    from backend.services.geo_coords import gcj02_to_wgs84
    ln = str(line_obj.get("ln") or "?")
    color = line_obj.get("c") if isinstance(line_obj.get("c"), str) and line_obj.get("c").startswith("#") else None
    if not color:
        m = re.search(r"(\d+)", ln)
        color = LINE_COLORS.get((city_norm, m.group(1) if m else "?"), "#2b6cb0")
    stations = []
    coords_wgs = []
    for s in line_obj.get("st", []):
        sl = str(s.get("sl") or "")
        parts = sl.split(",")
        if len(parts) != 2:
            continue
        try:
            lng, lat = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        wlng, wlat = gcj02_to_wgs84(lng, lat)
        coords_wgs.append([wlng, wlat])
        stations.append({
            "type": "Feature",
            "properties": {"name": s.get("n"), "line": ln,
                           "transfer": bool(s.get("su")), "color": color},
            "geometry": {"type": "Point", "coordinates": [wlng, wlat]},
        })
    if len(coords_wgs) < 2:
        return None, [], color
    line_feat = {
        "type": "Feature",
        "properties": {"name": ln, "line": ln, "color": color, "kind": "metro_line"},
        "geometry": {"type": "LineString", "coordinates": coords_wgs},
    }
    return line_feat, stations, color


def intl_relation_to_features(rel, elements_by_id):
    """OSM relation -> list[(line_feature, station_features, color)]（一条 relation 可能双向/多支）"""
    tags = rel.get("tags", {})
    ref = str(tags.get("ref") or tags.get("name") or "?")
    color = tags.get("colour") if isinstance(tags.get("colour"), str) and tags.get("colour").startswith("#") else "#8e44ad"
    members = rel.get("members", [])
    ways = []
    station_ids = set()
    for m in members:
        if m.get("type") == "way" and m.get("role") in ("", "rt"):
            ways.append(m.get("ref"))
        elif m.get("type") == "node" and m.get("role") in ("", "stop", "station"):
            station_ids.add(m.get("ref"))
    # 拼 polyline：按成员顺序连接各 way 的坐标
    coords = []
    for wid in ways:
        way = elements_by_id.get(wid)
        if not way:
            continue
        for nd in way.get("nodes", []):
            nde = elements_by_id.get(nd)
            if nde and "lat" in nde:
                coords.append([nde["lon"], nde["lat"]])
    stations = []
    for nid in station_ids:
        nde = elements_by_id.get(nid)
        if not nde or "lat" not in nde:
            continue
        stations.append({
            "type": "Feature",
            "properties": {"name": (nde.get("tags") or {}).get("name", ""), "line": ref, "color": color},
            "geometry": {"type": "Point", "coordinates": [nde["lon"], nde["lat"]]},
        })
    if len(coords) < 2:
        return []
    line_feat = {
        "type": "Feature",
        "properties": {"name": ref, "line": ref, "color": color, "kind": "metro_line"},
        "geometry": {"type": "LineString", "coordinates": coords},
    }
    return [(line_feat, stations, color)]


def build_metro_layers(city_norm, line_filter=""):
    """主入口：返回 (layers, summary)。layers = [{name, geojson, style}]"""
    is_cn = city_norm in CN_CITY_CODES
    line_layers = []
    station_feats = []
    seen_lines = []
    total_stations = 0
    endpoints = []

    if is_cn:
        data = fetch_cn(city_norm)
        for lo in data.get("l", []):
            ln = str(lo.get("ln") or "")
            if not line_matches(ln, line_filter):
                continue
            lf, sts, color = cn_line_to_features(lo, city_norm)
            if lf is None:
                continue
            line_layers.append(lf)
            station_feats.extend(sts)
            seen_lines.append(ln)
            total_stations += len(sts)
            if sts:
                endpoints.append("%s: %s  %s" % (ln, sts[0]["properties"]["name"], sts[-1]["properties"]["name"]))
    else:
        rels = fetch_intl(city_norm)  # tags 版：仅 relation 元数据（快、稳）
        for rel_meta in rels:
            rel_id = rel_meta["id"]
            tags0 = rel_meta.get("tags", {})
            ln_name = str(tags0.get("ref") or tags0.get("name") or "")
            if not line_matches(ln_name, line_filter):
                continue
            # 逐条拉 full（relation + 成员 way + node 坐标），单条失败跳过
            try:
                d = _overpass_post('[out:json][timeout:90];(relation(%d);>;);out body;' % rel_id)
            except Exception:
                continue
            by_id = {e["id"]: e for e in d.get("elements", [])}
            rel_full = by_id.get(rel_id) or rel_meta
            for lf, sts, color in intl_relation_to_features(rel_full, by_id):
                line_layers.append(lf)
                station_feats.extend(sts)
                if ln_name and ln_name not in seen_lines:
                    seen_lines.append(ln_name)
                total_stations += len(sts)

    if not line_layers:
        raise ValueError("城市「%s」未找到匹配「%s」的地铁线路" % (city_norm, line_filter or "全部"))

    layers = []
    for lf in line_layers:
        lname = "%s地铁%s" % (city_norm, lf["properties"]["line"])
        layers.append({"name": lname, "geojson": {"type": "FeatureCollection", "features": [lf]},
                       "style": {"color": lf["properties"]["color"], "weight": 4}})
    if station_feats:
        station_style = {"radius": 5}
        if len(line_layers) == 1:
            # 单线查询：站点用该线官方色，与线路本体一致（换乘站由 feature.transfer 区分）
            station_style["color"] = line_layers[0]["properties"]["color"]
            station_style["fillColor"] = line_layers[0]["properties"]["color"]
        layers.append({"name": "%s地铁站点" % city_norm,
                       "geojson": {"type": "FeatureCollection", "features": station_feats},
                       "style": station_style})
    _src_note = ("来源：高德地铁（官方商业数据，坐标已转 WGS-84）" if is_cn
                 else "来源：OSM 开源数据（志愿者维护，国际城市完整度参差，建议仅作示意参考，"
                      "权威线路请以当地交通机构 GTFS/官网为准）")
    summary = "%s 地铁：%s（共 %d 条线 %d 站）" % (
        city_norm, "、".join(seen_lines[:8]) + ("" if len(seen_lines) > 8 else ""),
        len(seen_lines), total_stations)
    if endpoints:
        summary += "；" + "；".join(endpoints[:3])
    summary += "\n（" + _src_note + "）"
    return layers, summary
