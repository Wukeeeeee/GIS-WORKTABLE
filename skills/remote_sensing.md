# 遥感影像处理技能参考

用 rasterio + numpy + scikit-learn 在本地处理遥感影像（无需 GEE，无需联网）。

## 可用 Python 库
- `rasterio` — 读写 GeoTIFF，波段操作
- `rioxarray` — 基于 xarray 的栅格处理
- `numpy` — 波段运算
- `matplotlib` — 渲染影像图
- `scikit-learn` — 监督分类
- `geopandas` — 分类结果转矢量

## 读取影像
```python
import rasterio
import numpy as np

with rasterio.open('input.tif') as src:
    data = src.read()           # shape: (波段数, 高, 宽)
    profile = src.profile       # 元数据（仿射变换、CRS 等）
    bounds = src.bounds         # 边界（left, bottom, right, top）
```

## 波段运算（植被指数等）
```python
# NDVI = (近红外 - 红) / (近红外 + 红)
red = data[3].astype(float)    # 红波段（通常是 band 4）
nir = data[7].astype(float)    # 近红外（通常是 band 8）
ndvi = (nir - red) / (nir + red + 1e-10)

# NDWI = (绿 - 近红外) / (绿 + 近红外)
green = data[2].astype(float)
ndwi = (green - nir) / (green + nir + 1e-10)
```

## 显示到聊天框
```python
import matplotlib.pyplot as plt

plt.figure(figsize=(10, 8))
plt.imshow(ndvi, cmap='RdYlGn', vmin=-1, vmax=1)
plt.colorbar(label='NDVI')
plt.title('NDVI')
plt.savefig('output/ndvi_result.png', dpi=200, bbox_inches='tight')
# 图片会自动显示在前端
```

## 加载到地图（栅格切片预览）
```python
# 将处理结果转为 PNG 瓦片风格，通过 matplotlib 显示
# 前端会显示 PNG 图片在聊天框
# 注意：真正的栅格切片需要额外 Tile Server 支持
# 简单预览用 plt.savefig 即可
```

## 加载到地图（分类结果转矢量）
```python
# 监督分类后的结果可以转 GeoJSON 加载到地图
from rasterio.features import shapes
import geopandas as gpd
from shapely.geometry import shape

mask = classified == 1  # 筛出某个类别
results = ({'properties': {'class': int(v)}, 'geometry': s}
           for s, v in shapes(classified.astype(np.int32), mask=mask))
gdf = gpd.GeoDataFrame.from_features(list(results), crs=src.crs)
gdf = gdf.to_crs('EPSG:4326')

import json
geojson = json.loads(gdf.to_json())
print(json.dumps(geojson, ensure_ascii=False))
# GeoJSON 自动加载到前端地图
```

## 监督分类（Random Forest）
```python
from sklearn.ensemble import RandomForestClassifier
import numpy as np

# 准备训练数据：每行是一个像素的所有波段值
bands = data[:6].astype(float)  # 取前 6 个波段
h, w = bands.shape[1], bands.shape[2]
X = bands.reshape(len(bands), -1).T  # (像素数, 波段数)

# 训练样本（手动选取或从矢量文件读取）
train_pixels = np.array([
    # [b1, b2, b3, b4, b5, b6, label]
])
X_train = train_pixels[:, :-1]
y_train = train_pixels[:, -1]

# 训练
clf = RandomForestClassifier(n_estimators=100, random_state=42)
clf.fit(X_train, y_train)

# 预测
y_pred = clf.predict(X)
classified = y_pred.reshape(h, w)

# 结果转矢量加载到地图（见上方"分类结果转矢量"）
```

## 获取影像数据
- **本地文件**：用户上传 GeoTIFF → 保存在 `output/uploads/`
- **地理空间数据云** (gscloud.cn)：用 `search_web` 搜索下载链接
- **Copernicus Open Access Hub**：用 `scrape_page` 搜索
- 下载后路径：`output/uploads/文件名.tif`

## 注意事项
- 遥感影像通常较大，处理时先用小范围测试
- 每次输出结果后及时保存，避免内存溢出
- 分类结果建议转矢量 GeoJSON 加载到地图（更轻量）
- 全色影像做监督分类时，先做 PCA 降维再分
