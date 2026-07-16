# GDAL 地理数据处理技能参考

用 GDAL 命令行工具处理栅格和矢量数据。

## 可用工具
`gdalinfo`, `gdal_translate`, `gdalwarp`, `gdal_merge.py`, `gdal_polygonize.py`, `ogr2ogr`, `ogrinfo`

## 常用操作
```bash
gdal_translate -of COG input.tif output.tif       # 转 Cloud Optimized GeoTIFF
gdalwarp -t_srs EPSG:4326 input.tif output.tif     # 栅格转 WGS-84
gdalwarp -cutline boundary.geojson -crop_to_cutline input.tif output.tif  # 裁剪
ogr2ogr -f GeoJSON output.geojson input.shp          # Shapefile → GeoJSON
ogr2ogr -t_srs EPSG:4326 output.shp input.shp       # 矢量转 WGS-84
```

## 输出到地图
GDAL 生成的 GeoJSON 可以直接 print 到前端加载。