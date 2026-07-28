<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GeoMind" width="320">
</p>

<p align="center">
  <b>地理空间分析工作台 · AI 驱动的 GIS 工具</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=flat-square&logo=javascript&logoColor=black" />
  <img src="https://img.shields.io/badge/Leaflet-199900?style=flat-square&logo=leaflet&logoColor=white" />
  <img src="https://img.shields.io/badge/License-AGPL%20v3-1a1a2e?style=flat-square" />
</p>

---

一个基于 Web 的 GIS 数据处理与可视化工作台，内置三模型 AI Agent，通过自然语言对话即可驱动地图操作、空间分析、栅格处理和数据加载。**目标：复刻 ArcGIS 核心功能，全部通过自然语言调用。**

## 截图

![界面截图](firstHtml.png)

## 快速开始

```bash
# 安装后端依赖
cd backend
pip install -r requirements.txt

# 启动服务
cd ..
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

打开浏览器访问 `http://localhost:8000`。

## 功能一览（80+ 功能，全部可自然语言调用）

### 数据加载
GeoJSON / Shapefile（ZIP）/ GeoPackage / KML / GPX / CSV 经纬度转点 / GeoTIFF / 数据预览

### 图层管理
浮动面板（显隐/排序/分组/重命名/删除）/ 右键菜单 / 独立颜色/透明度/线宽 / 面填充样式（斜线/网格/点阵）

### 符号化
分级设色（6 色带）/ 唯一值渲染 / 标注（字段值 tooltip）/ 图例

### 属性表
弹出面板 / 排序筛选 / CSV 导出 / 字段统计 / 按属性选择 / 字段计算 / 添加/删除字段 / 属性编辑

### 自然语言编辑
移动 / 旋转 / 缩放 / 缓冲区 / 分割 / 合并 / 删除要素

### 绘制
点 / 线 / 面 / 矩形 / 圆 / 折点编辑 / 捕捉 / 撤销重做 / 测距测面积

### 空间分析
缓冲区 / 相交 / 合并 / 裁剪 / 差异 / 质心 / 简化 / 融合(Dissolve) / 空间连接 / 图层拆分 / 图层合并 / 空间选择 / 随机采样 / 邻近查找 / DBSCAN 聚类 / 泰森多边形 / 多点缓冲区 / 字段统计 / 反向地理编码

### 网络分析
**面板**：最短路径（途经点/方向箭头）/ 服务区（多级断值）/ 最近设施（混合选点）
**AI 驱动**：自然语言 → 下载路网 → 分析 → 加载结果，全流程自动

### 栅格分析
**DEM 地形**：坡度 / 坡向 / 山体阴影（Horn 公式，不依赖 GDAL）
**提取**：等高线（skimage）/ 水文分析（流向/流量/河网提取）
**计算**：NDVI / 栅格计算器（波段算术 + 数学函数）
**插值**：IDW / RBF

### 质量控制
拓扑检查（重叠/缝隙/无效几何）/ 批量处理链

### 制图导出
图例 / 比例尺 / 指北针 / 图片导出（PNG/JPEG）/ PDF 出图（A4 横向）/ Shapefile / GeoPackage / CSV 导出

### AI Agent 系统
- 三模型支持：**GLM-4.7-Flash+**（免费默认）、**DeepSeek V4 Flash+**、**Agnes 2.0 Flash+**
- LangGraph 驱动的 ReAct Agent，自动管理多轮工具调用
- GLM 路由系统，自动加载技能文档辅助任务
- SSE 流式响应，前端实时展示工具调用进度

### 第三方数据
高德 POI 搜索 / 地理编码 / 行政边界（DataV）/ 百度 AOI 建筑轮廓 / OSM 路网 / 热力图

## 项目结构

```
frontend/
├── index.html              # 主页面（菜单栏 + 绘图工具栏 + 图层面板）
├── css/style.css            # 样式
└── js/
    ├── app.js              # 应用初始化
    ├── chat.js             # AI 对话 + 斜杠命令面板
    ├── map.js              # 地图控制 + 菜单栏交互
    ├── layers.js           # 图层面板 + 样式控制
    ├── settings.js         # 设置弹窗
    ├── task.js             # 任务管理
    ├── api.js              # API 通信
    ├── upload.js           # 文件上传
    ├── aoi.js              # AOI 交互
    ├── network.js          # 网络分析面板
    ├── spatial.js          # 空间分析面板
    ├── debug.js            # 调试面板
    ├── project.js          # 工程持久化
    └── time.js             # 时序动画

backend/
├── main.py                 # FastAPI 入口
├── tests/
│   └── test_spatial_tools.py  # 195 个测试
└── services/
    ├── ai_service.py       # AI 服务层
    ├── graph.py            # LangGraph Agent
    ├── tools.py            # 31 个 @tool 工具（核心逻辑）
    ├── layer_service.py
    ├── amap_service.py
    ├── baidu_aoi_service.py
    ├── datav_service.py
    ├── geo_coords.py
    ├── log_service.py
    ├── network_service.py
    └── project_service.py

goal/                       # 项目目标与进度
├── goal.md                 # 更新日志
└── features.md             # 功能清单（全部完成）

test/                       # 测试数据与报告
├── test_plan.md            # 测试计划
├── data/                   # 测试数据（自动生成）
└── reports/                # 测试报告（自动生成）
```

## 技术栈

| 类别 | 技术 |
|------|------|
| 前端 | HTML + CSS + JavaScript |
| 地图 | Leaflet + Leaflet.Draw |
| 后端 | FastAPI + Python |
| AI 框架 | LangGraph (ReAct Agent) |
| 模型 | GLM-4.7-Flash+ / DeepSeek V4 Flash+ / Agnes 2.0 Flash+ |
| GIS | GeoPandas + Shapely + PyProj + Rasterio |
| 栅格 | NumPy + scikit-image + Matplotlib |

## 更新日志

### 2026-07-28
- 坐标转换/投影工具：WGS84 / Web Mercator / UTM 互转
- 地形剖面工具：沿线采样 → matplotlib 折线图
- 3D 地形：Three.js 嵌入 HTML 展示 DEM
- 时序动画：按时间字段逐帧播放
- 图表联动：选中要素高亮图表、点击图表聚焦要素
- 水文分析：D8 算法（填洼→流向→汇流累积量→河网）
- 拓扑检查：检测重叠/缝隙/无效几何
- 空间插值：IDW / RBF 插值
- 栅格计算器：波段算术 + 数学函数
- NDVI 计算：多光谱植被指数
- 等高线提取：skimage 从 DEM 提取
- DEM 分析：坡度/坡向/山体阴影（Horn 公式）
- 地质剖面：三维地形纵断面分析
- 多点缓冲区
- 测距工具
- 属性标注（tooltip）
- 图例组件
- 指北针
- 绘制工具：点/线/面/矩形/圆
- 折点编辑 / 捕捉 / 撤销重做
- 移动/旋转/缩放要素
- 按属性选择 / 属性编辑 / 添加删除字段
- Shapefile/GeoPackage 上传
- CSV/Excel 经纬度转点
- GeoTIFF 栅格加载
- 数据预览弹窗
- 独立颜色/透明度/线宽
- 面填充样式（斜线/网格/点阵）
- 图层分组 / 右键菜单
- PDF 出图 / 图片导出
- Shapefile/GPKG/CSV 导出
- 斜杠命令面板新增 17 个命令
- 顶部菜单栏新增「栅格」菜单
- 195 个测试全通过

### 2026-07-27
- Main 测试网络分析面板
- Fix 操作手册 HTML 结构断裂导致地图不加载：补回 4 个缺失的 `</div>` 闭合标签
- Fix 手册中 emoji 图标统一替换为 SVG
- Fix AI 工具路由：`execute_python` docstring 改为"最后选择"、系统提示词新增工具优先级规则
- Fix `_push_layer` 推图层不生效：`get_pending_state()` 改为读取即消费 + 线程锁，修复校验器路径图层重复累积
- Fix SSE 端点冗余 `reset_state` 调用，`run_agent_stream` `msgs` 变量初始化
- Update 操作手册：新增空间分析 section（网络分析/AOI/行政边界/热力图）、AI 斜杠命令完整表格（18 条）、图层管理补充导出/字段计算/图表、顶部菜单更新
- Add 网络分析面板单元测试（26 项）
- Add 网络分析面板重构（三栏结构，与设置弹窗风格统一）
- Add 面板拖拽约束（左边界限定在聊天面板右侧，底部限 vh-10）
- Add 导入性能优化：json.loads/gpd.read_file 移至线程池，SHP/GPKG/KML 路径省掉 JSON 序列化往返
- Fix 选点卡死：snap 失败时重置 _inputMode 和光标
- Fix 后端 error 字段被忽略：路网为空时显示具体错误
- Fix 面板关闭后 _initialized 被重置导致每次打开全量重建 DOM
- Fix 导出空白：_exportResult 调用 addLayer 传参错误
- Fix 方向箭头 ▶ 残留：添加 _arrowMarker 变量跟踪并随结果清理

### 2026-07-21
- ...

详见完整更新日志 [`goal/goal.md`](goal/goal.md)。

## 许可证

AGPL v3 — 详见 [LICENSE](LICENSE)。
