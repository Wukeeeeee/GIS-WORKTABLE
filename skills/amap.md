# 高德地图 Web API 技能

用高德地图 Web 服务 API 获取 POI、天气、地理编码等数据。

## 坐标系统
- 高德 API 返回的坐标均为 **GCJ-02**（国测局坐标）
- 加载到地图前需转为 **WGS-84**，用以下公式：
```python
import math
def gcj02_to_wgs84(lng, lat):
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
    return lng - dlng, lat - dlat

def _transform_lat(lng, lat):
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * math.pi) + 40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320.0 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return ret

def _transform_lng(lng, lat):
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * math.pi) + 40.0 * math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 * math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
    return ret
```

## API Key
高德地图 Web API Key 通过 `__AMAP_KEY__` 变量获取（后端注入），用 `requests` 调用。

## 可用 API 列表

### 1. 关键字搜索 POI
```
GET https://restapi.amap.com/v3/place/text
```
参数：
- `key` — API Key（必填）
- `keywords` — 查询关键字（与 types 二选一必填）
- `types` — POI 类型编码（与 keywords 二选一必填）
- `city` — 城市（中文/citycode/adcode，可选）
- `citylimit` — true/false，仅返回指定城市数据
- `offset` — 每页条数，**强烈建议不超过25**
- `page` — 页码
- `extensions` — base（默认）/ all（返回附近POI、道路等）

分页说明：同请求参数翻页最多获取 **200 条**数据（offset=25, page=1~8）。
建议每页取 25 条（offset=25），逐页遍历（page=1,2,3...）。使用 `count` 字段判断总条数。

### 2. 周边搜索 POI
```
GET https://restapi.amap.com/v3/place/around
```
参数：
- `key`, `keywords`, `types`, `offset`, `page`, `extensions` — 同上
- `location` — 中心点经纬度（必填，经度,纬度）
- `radius` — 搜索半径，单位米，0-50000
- `sortrule` — distance（按距离）/ weight（综合）
- `city` — 查询城市

### 3. 多边形搜索 POI
```
GET https://restapi.amap.com/v3/place/polygon
```
参数：
- `key`, `keywords`, `types`, `offset`, `page`, `extensions` — 同上
- `polygon` — 经纬度坐标对（必填），经度,纬度|经度,纬度|...
  矩形时可传左上右下两顶点；其他情况首尾坐标相同

### 4. ID 查询 POI 详情
```
GET https://restapi.amap.com/v3/place/detail
```
参数：
- `key`, `id`（POI ID，必填）

### 5. 天气查询
```
GET https://restapi.amap.com/v3/weather/weatherInfo
```
参数：
- `key` — API Key（必填）
- `city` — 城市 adcode（必填）
- `extensions` — base（实况天气）/ all（预报天气）
- 预报天气每天更新 3 次（8/11/18 点左右）

返回：`lives`（实况：temperature/winddirection/windpower/humidity），`forecast`（预报：dayweather/nightweather/daytemp/nighttemp）

### 6. 地理编码（地址→坐标）
```
GET https://restapi.amap.com/v3/geocode/geo
```
参数：
- `key`, `address`（结构化地址，必填）
- `city`（指定查询城市）
返回：`geocodes[].location`（经度,纬度，GCJ-02）

### 7. 逆地理编码（坐标→地址）
```
GET https://restapi.amap.com/v3/geocode/regeo
```
参数：
- `key`, `location`（经度,纬度，必填）
- `radius`（搜索半径，0-3000米）
- `extensions` — base / all（返回附近POI/道路/交叉口）
返回：`regeocode.addressComponent`（province/city/district/...），`regeocode.pois`（附近POI）

### 8. 行政区域查询
```
GET https://restapi.amap.com/v3/config/district
```
参数：
- `key`, `keywords`（关键词，必填）
- `subdistrict` — 子级行政区 0/1/2/3
- `extensions` — base / all（返回边界坐标）
返回：`districts[].adcode`, `districts[].polyline`（边界坐标串）

## POI 分类编码
大类（前2位）：010000=汽车服务, 020000=汽车销售, 030000=汽车维修, 040000=摩托车服务,
050000=餐饮服务, 060000=购物服务, 070000=生活服务, 080000=体育休闲服务,
090000=医疗保健服务, 100000=住宿服务, 110000=风景名胜, 120000=商务住宅,
130000=政府机构, 140000=科教文化服务, 150000=交通设施服务, 160000=金融保险服务,
170000=公司企业, 180000=道路附属设施, 190000=地名地址信息, 200000=公共设施

### 9. 高程查询（DEM）
```
GET https://restapi.amap.com/v3/elevation
```
参数：
- `key` — API Key（必填）
- `locations` — 经纬度坐标，格式 `lng,lat` 或 `lng,lat|lng,lat|...`，**最多 20 个点**
返回：`elevation[]` 中每个元素包含 `location`（经度,纬度）和 `elevation`（海拔高度，米）

注：高程查询已在 `get_elevation` 工具中封装，AI 可直接调用，支持按 bbox 范围生成网格批量查询。

## 使用工作流
1. 将用户需求对应到上述 API
2. 用 `requests.get(url, params)` 调用，API Key 用 `__AMAP_KEY__` 变量
3. 将返回的 JSON 数据中的 GCJ-02 坐标转成 WGS-84（用上面的函数）
4. 打印 GeoJSON 加载到地图，或用表格/图表展示
5. 高德 API 的 offset 参数每页建议 25 条，需分页时用 page 翻页，最多翻到 200 条
