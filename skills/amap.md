# 高德地图 Web API 技能

用高德地图 Web 服务 API 获取 POI、天气、地理编码等数据。

## 坐标系统（重要）
- 高德 API 返回的坐标均为 **GCJ-02**（国测局坐标）
- **必须转 WGS-84** 才能加载到地图，用以下代码（直接复制使用）：

```python
import math
def gcj02_to_wgs84(lng, lat):
    a = 6378245.0; ee = 0.00669342162296594323
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat); magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lng - dlng, lat - dlat
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
    ret += (150.0*math.sin(lng/12.0*math.pi) + 300.0*math.sin(lng/30.0*math.pi)) * 2.0/3.0
    return ret
```

## API Key
高德地图 Web API Key 通过 `os.environ.get('AMAP_KEY', '')` 获取。

## 可用 API 列表

### 1. 关键字搜索 POI
`GET https://restapi.amap.com/v3/place/text`
参数：key, keywords/types, city, citylimit, offset(≤25), page, extensions
**安全约束：** 同参数最多获取 **200 条**（offset=25, page=1~8），绝对不要一次取太多

### 2. 周边搜索 POI
`GET https://restapi.amap.com/v3/place/around`
参数：key, keywords/types, location(必填), radius(0-50000), sortrule, city, offset, page

### 3. 多边形搜索 POI
`GET https://restapi.amap.com/v3/place/polygon`
参数：key, keywords/types, polygon, offset, page

### 4. ID 查询 POI 详情
`GET https://restapi.amap.com/v3/place/detail`
参数：key, id

### 5. 天气查询
`GET https://restapi.amap.com/v3/weather/weatherInfo`
参数：key, city(adcode), extensions(base实况/all预报)

### 6. 地理/逆地理编码
`GET https://restapi.amap.com/v3/geocode/geo` — 地址→坐标
`GET https://restapi.amap.com/v3/geocode/regeo` — 坐标→地址

### 7. 行政区域查询
`GET https://restapi.amap.com/v3/config/district`
参数：key, keywords, subdistrict(0-3), extensions(base/all)

## POI 分类编码
大类（前2位）：010000=汽车服务, 050000=餐饮服务, 060000=购物服务, 070000=生活服务,
080000=体育休闲, 090000=医疗保健, 100000=住宿服务, 110000=风景名胜, 120000=商务住宅,
130000=政府机构, 140000=科教文化, 150000=交通设施, 160000=金融保险, 170000=公司企业

## 使用策略
- **优先用 search_web 搜公开 POI 信息省额度**，找不到再用 amap_poi_search
- 搜索时**必须指定 city 参数**缩小范围
- offset 每页 25 条，同参数翻页最多获取 200 条
- **禁止用 execute_python 调高德 Web API**（坐标转换易出错且浪费额度）

## 使用工作流（安全顺序）
1. 用 `requests.get(url, params)` 调用，API Key 从 `os.environ.get('AMAP_KEY', '')` 获取
2. **必须**用上面的 `gcj02_to_wgs84()` 转坐标，**绝对不能**直接用 GCJ-02 坐标加载地图
3. 打印 GeoJSON 加载到地图