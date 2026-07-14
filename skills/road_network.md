# 路网获取

用 OSMnx + Overpass 国内镜像获取道路网络数据，合法且国内直连。

## 基础用法

```python
import osmnx as ox

# 按地名获取路网（城市/区县/自定义区域）
G = ox.graph_from_place('北京市海淀区', network_type='drive')

# 边 → GeoJSON → 加载到地图
edges = ox.graph_to_gdfs(G, nodes=False)
print(edges.to_json())        # 自动推送到地图

# 节点（路口）也可以单独拿
nodes = ox.graph_to_gdfs(G, edges=False)
```

## network_type 参数

| 值 | 含义 |
|------|------|
| `drive` | 机动车道路 |
| `walk` | 步行道路 |
| `bike` | 自行车道 |
| `drive_service` | 机动车 + 服务道路 |
| `all` | 所有道路 |

## 高级用法

```python
# 按多边形范围获取
import geopandas as gpd
from shapely.geometry import box
poly = box(116.3, 39.8, 116.5, 40.0)    # 经纬度范围
G = ox.graph_from_polygon(poly, network_type='drive')

# 统计路网指标
edges = ox.graph_to_gdfs(G, nodes=False)
total_km = edges['length'].sum() / 1000
print(f'总道路长度：{total_km:.1f} km')

# 按道路类型分组统计
road_stats = edges.groupby('highway')['length'].sum() / 1000
print(road_stats)
```

## 注意

- Overpass 镜像地址已在 execute_python 环境初始化中自动设置（5 个镜像自动切换，选最快的），无需手动配置
- 查询范围不要太大（建议一个区/县城级别），否则超时（当前超时限制 120s）
- 返回的边自带 `name`（道路名）、`highway`（道路类型）、`length`（长度，米）等字段
- 数据坐标系为 WGS-84 (EPSG:4326)，可直接上地图
- 国外城市同样支持，无需翻墙
- OSM 在中国数据不完整（城市尚可，乡村缺失），如需要官方权威数据，考虑天地图 WFS
