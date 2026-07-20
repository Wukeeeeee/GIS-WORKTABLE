# 路网获取

用 OSMnx + Overpass 国内镜像获取道路网络数据。

## 基础用法
```python
import osmnx as ox
G = ox.graph_from_place('北京市海淀区', network_type='drive')
edges = ox.graph_to_gdfs(G, nodes=False)
print(edges.to_json())        # 自动推送到地图
```

## network_type 参数
`drive`(机动车) / `walk`(步行) / `bike`(自行车) / `drive_service` / `all`

## 高级用法
```python
# 按多边形范围获取
from shapely.geometry import box
G = ox.graph_from_polygon(box(116.3, 39.8, 116.5, 40.0), network_type='drive')

# 统计路网指标
edges = ox.graph_to_gdfs(G, nodes=False)
total_km = edges['length'].sum() / 1000
```

## network_analysis 工具（基于已有路网图层做分析）
有路网图层后，用 `network_analysis` 工具做分析：
- **route**（最短路径）：传 origin + destination
- **service_area**（服务区）：传 facility + breaks（逗号分隔米数）
- **closest_facility**（最近设施）：传 origin + events（分号分隔坐标）

坐标参数统一格式：`"经度,纬度"`

## 注意
- Overpass 镜像地址已在 execute_python 环境初始化中自动设置，无需手动配置
- 查询范围不要太大（建议一个区/县城级别），否则超时（当前超时限制 120s）
- 返回的边自带 `name`（道路名）、`highway`（道路类型）、`length`（长度，米）等字段
- 数据坐标系为 WGS-84 (EPSG:4326)，可直接上地图
- 国外城市同样支持，无需翻墙