# ArcGIS 功能对照清单

`[ ]` = 待做，`[x]` = 已完成

## 数据加载
- [x] Shapefile 上传（.shp+.dbf+.prj，打包为 ZIP）
- [x] GeoPackage 上传
- [x] CSV/Excel 经纬度转点（上传后 AI 自动调用 layer_add_geometry）
- [x] GeoTIFF 栅格加载
- [x] 数据预览（上传前 CSV/GeoJSON 文件头弹窗预览，确认后上传）

## 属性表
- [x] 属性表面板（点击要素弹出属性，含定位）
- [x] CSV 导出
- [x] 字段统计
- [x] 按属性选择

## 图层样式
- [x] 独立颜色 / 透明度 / 线宽（layer_control set_style，AI 自然语言可调用）
- [x] 面填充样式（斜线/网格/点阵/十字/对角线，set_style fill_pattern）
- [x] 分级设色
- [x] 唯一值渲染
- [x] 标注

## 自然语言编辑
- [x] 移动要素
- [x] 旋转要素
- [x] 缩放要素
- [x] 缓冲区
- [x] 分割 / 合并
- [x] 删除要素

## 空间分析
- [x] 空间连接
- [x] 融合/Dissolve
- [x] 邻近分析
- [x] 泰森多边形
- [x] 多点缓冲区

## 绘制
- [x] 绘制点 / 线 / 面（AI 自然语言可调用，draw_feature 工具）
- [x] 矩形 / 圆（draw_feature 扩展，Rectangle/Circle）
- [x] 折点编辑
- [x] 捕捉
- [x] 撤销重做
- [x] 测距测面积

## 制图
- [x] 图例
- [x] 比例尺
- [x] 指北针
- [x] PDF 出图
- [x] 图片导出

## 导出
- [x] Shapefile 导出
- [x] GPKG 导出
- [x] CSV/Excel 导出

## 图层管理
- [x] 排序拖拽
- [x] 分组
- [x] 右键菜单
- [x] 重命名

## 栅格
- [x] 坡度 / 坡向 / 山体阴影
- [x] 等高线
- [x] NDVI
- [x] 栅格计算器

## 数据管理
- [x] 字段计算
- [x] 添加/删除字段
- [x] 属性编辑

## 高级
- [x] 插值（IDW / 克里金）
- [x] 拓扑检查
- [x] 水文分析
- [x] 批量处理链
- [x] 3D 地形
- [x] 时序动画
- [x] 图表联动
