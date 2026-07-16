# 遥感影像处理技能参考

用 rasterio + numpy + scikit-learn 在本地处理遥感影像。

## 可用 Python 库
`rasterio`, `numpy`, `matplotlib`, `scikit-learn`, `geopandas`

## 读取影像
```python
with rasterio.open('input.tif') as src:
    data = src.read()           # shape: (波段数, 高, 宽)
    profile = src.profile       # 元数据（仿射变换、CRS 等）
    bounds = src.bounds         # 边界
```

## 波段运算 —— 安全代码模板（直接套用）
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
plt.imshow(ndvi, cmap='RdYlGn', vmin=-1, vmax=1)
plt.colorbar(label='NDVI')
plt.savefig('output/ndvi_result.png', dpi=200, bbox_inches='tight')
```

## 分类结果转矢量加载到地图
```python
from rasterio.features import shapes
mask = classified == 1  # 筛出某个类别
results = ({'properties': {'class': int(v)}, 'geometry': s}
           for s, v in shapes(classified.astype(np.int32), mask=mask))
gdf = gpd.GeoDataFrame.from_features(list(results), crs=src.crs)
gdf = gdf.to_crs('EPSG:4326')
print(gdf.to_json())
```

## 监督分类（Random Forest）
```python
from sklearn.ensemble import RandomForestClassifier
X = bands.reshape(len(bands), -1).T  # (像素数, 波段数)
clf = RandomForestClassifier(n_estimators=100, random_state=42)
clf.fit(X_train, y_train)
classified = clf.predict(X).reshape(h, w)
```

## 注意
- 遥感影像通常较大，处理时先用小范围测试
- 分类结果建议转矢量 GeoJSON 加载到地图（更轻量）
- **绝对不要用 WGS84 坐标直接算面积**，先投影到等面积投影