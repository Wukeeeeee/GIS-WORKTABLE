<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GIS WorkTable" width="320">
</p>

<p align="center">
  GIS WORKTABLE
</p>

> 更新时间：2026-07-02

## 设计演进

<p align="center">
  <img src="firstDesign.jpg" alt="设计稿" width="80%">
</p>

<p align="center">
  <img src="DESIGNMD.png" alt="色彩方案" width="80%"><br>
  <a href="DESIGN.md">色彩方案配置</a>
</p>

<p align="center">
  <img src="firstHtml.png" alt="实际界面" width="80%">
</p>

利用 Google Stitch 设计界面，完成前端界面骨架搭建：

- Leaflet 地图集成（OSM 底图 + 天地图预留）
- 左侧聊天面板
- 底部图层列表（拖拽排序、显隐、删除）
- 文件上传交互与格式校验
- 处理结果展示区域
- API 接口已预留，待后端接入

## 目录结构

```
Gis-WorkTable/
└── frontend/
    ├── index.html
    ├── css/style.css
    ├── js/
    └── assets/icons.svg
```

## 未来规划

- 后端服务（FastAPI + 空间分析引擎）
- AI 对话对接（自然语言转 GIS 操作）
- 多图层叠加分析
- 属性表查看与编辑
- 坐标系投影转换
- 结果导出（GeoJSON / Shapefile）
- 支持栅格数据与遥感影像

## 免责声明

本项目使用 OpenStreetMap 作为默认底图。OSM 数据由全球用户贡献，部分国家、地区边界及地理信息的表述可能与官方承认的边界存在不一致，请使用者自行甄别。如需更准确的国内地图数据，建议申请天地图 API 密钥并在 `map.js` 中切换底图源。
