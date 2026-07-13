# GDAL 地理数据处理技能参考

[![Source](https://img.shields.io/badge/Source-GDAL__Geospatial__Skill-2ea44f?style=flat-square)](https://mcpmarket.com/zh/tools/skills/gdal-geospatial-processing)

用 GDAL 命令行工具处理栅格和矢量数据。

## 可用工具
- `gdalinfo` — 查看栅格数据信息
- `gdal_translate` — 格式转换、裁剪、重采样
- `gdalwarp` — 投影转换、拼接、裁剪
- `gdal_merge.py` — 拼接多个栅格
- `gdal_polygonize.py` — 栅格转矢量
- `ogr2ogr` — 矢量格式转换、投影转换、筛选
- `ogrinfo` — 查看矢量数据信息

## 常用操作

### 栅格格式转换
```bash
gdal_translate -of COG input.tif output.tif       # 转 Cloud Optimized GeoTIFF
gdal_translate -of PNG input.tif output.png        # 转 PNG
```

### 投影转换
```bash
gdalwarp -t_srs EPSG:4326 input.tif output.tif     # 栅格转 WGS-84
ogr2ogr -t_srs EPSG:4326 output.shp input.shp       # 矢量转 WGS-84
```

### 裁剪栅格
```bash
gdalwarp -cutline boundary.geojson -crop_to_cutline input.tif output.tif
```

### 矢量格式转换
```bash
ogr2ogr -f GeoJSON output.geojson input.shp          # Shapefile → GeoJSON
ogr2ogr -f GeoJSON output.geojson input.gpkg         # GeoPackage → GeoJSON
```

### 查看数据信息
```bash
gdalinfo input.tif                                   # 栅格元数据
ogrinfo -al -so input.geojson                       # 矢量属性概览
```

## 输出到地图
GDAL 生成的 GeoJSON 可以直接 print 到前端加载。
