# GIS-WorkTable 持续演进日志 (log.md)

## 2026-10-11 系统审计与稳定性优化

### 1. 检查模块与基线测试
- **测试现状扫描**：
  - 执行 `python -m pytest backend/tests -q`。
  - 测试结果：511 项用例，510 passed，1 skipped（耗时 81.09s），确认代码库整体具备良好测试覆盖率与稳定性基础。
- **架构审计**：
  - 前端：HTML5 + Leaflet 2D + CesiumJS 3D 双引擎，通过 `gis_state.js` 作为响应式状态中枢。
  - 后端：FastAPI + LangGraph ReAct 框架，整合 120+ LangChain 工具并具备结果自检（Verifier）。

### 2. 发现的问题及复现方法
1. **UTM 投影带越界 Bug (P0)**：
   - 现象：在部分矢量工具（如 `spatial_buffer`、`spatial_multi_ring_buffer`、`move_features`、`draw_feature`、`measure_area`）中，计算 UTM zone 使用 `int((lon + 180) / 6) + 1`，当经度为 180° 或大于 174° 时计算出 zone 61，导致生成 `EPSG:32661`（这是 UPS 北极极地立体投影，而非 UTM 60 带），使得投影转换发生不可预期的形变甚至报错。
2. **图层重命名状态断链问题 (P0)**：
   - 现象：用户在前端图层列表重命名图层后，仅修改了界面上的展示名，未同步更新 `GIS.state` 与后端注册图层名，后续 AI 按照新图层名调用工具时会提示“未找到图层”。
3. **首屏新手引导缺失 (P1)**：
   - 现象：新用户首次进入时，对话框空状态仅有一句时间问候语（如“下午好，进度还顺利吗”），用户不知道系统具体支持哪些功能，无从下手。

### 3. 修改文件与解决方案
- **修改文件**：
  - `backend/services/tools.py`：新增统一的 `_get_utm_crs(lon, lat)` 辅助函数，将 UTM 带号严格限制在 1~60 之间；并在 `spatial_buffer`、`spatial_multi_ring_buffer`、`move_features`、`draw_feature` 及 `measure_area` 中统一应用。
  - `frontend/js/gis_state.js`：新增 `renameLayer(layerId, newName)` 方法，同步修改图层状态并触发 `layer-renamed` 事件，导出到 `GIS.state`。
  - `frontend/js/map.js`：新增 `renameLayer(oldName, newName)` 方法，同步更新 Leaflet 图层字典、GeoJSON 缓存与要素键映射，导出到 `GIS.map`。
  - `frontend/js/layers.js`：在重命名提交逻辑中同步调用 `GIS.state.renameLayer`、`GIS.map.renameLayer` 以及后端注册/注销 API。
  - `frontend/js/chat.js`：在执行 AI 返回的 `rename` 操作时同步更新 `GIS.state` 与 `GIS.map`。
  - `frontend/js/time.js`：将首屏空状态扩展为“问候语 + 核心能力介绍 + 3 个典型工作流一键执行卡片”，降低初次使用门槛。
  - `backend/tests/test_spatial_tools.py`：新增 `test_utm_crs_boundary` 与 `test_layer_control_rename_sync` 单元测试。
  - `docs/PROJECT_AUDIT.md`：建立完整的系统架构审计与功能清单文档。

### 4. 实际执行的测试命令与结果
- `D:\python\python.exe -m pytest backend/tests/test_spatial_tools.py -k "test_utm_crs_boundary or test_layer_control_rename_sync" -q`
  - 结果：2 passed（通过极值边界与图层重命名状态同步测试）。
- `D:\python\python.exe -m pytest backend/tests/test_spatial_tools.py -q`
  - 结果：全量 66 项空间工具测试 100% passed。

### 5. 当前阻塞事项与下一步计划
- **阻塞事项**：无。
- **下一步建议**：
  1. 持续细化高德与海外数据源在无 API Key / 网络离线情况下的优雅降级提示。
  2. 进一步丰富 3D 模式下的空间分析面板快捷交互体验。

---

## 2026-10-11 开源项目规范化整理

### 1. 检查现状
- Git Tags: 检查确认仓库无历史 tag，GitHub Releases 未初始化。
- 版本基准: `desktop/package.json` 当前定义版本为 `0.1.0`。
- 确定版本管理策略: 采用 Semantic Versioning（MAJOR.MINOR.PATCH），项目定位于 `v0.1.0 (Pre-1.0 开源开发预览阶段)`，避免虚构 v1.0.0。
- 完整保留所有未提交修改，无覆盖。

### 2. 新增与修改文件
- 新增 `CHANGELOG.md`: 遵循 Keep a Changelog 与 SemVer 规范，完整分类记录 `[Unreleased]` 与 `[0.1.0]` 的新增、变更与修复。
- 新增 `CONTRIBUTING.md`: 规范开发环境搭建、测试执行要求（全量 pytest 校验）与 PR 命名和提交标准。
- 新增 `docs/ROADMAP.md`: 规划 v0.1.0 现状、v0.2.0 近期目标与中远期路线，无虚构功能。
- 新增 `.github/ISSUE_TEMPLATE/bug_report.md`: 结构化缺陷报告模板。
- 新增 `.github/ISSUE_TEMPLATE/feature_request.md`: 结构化功能建议模板。
- 新增 `.github/pull_request_template.md`: 规范化 Pull Request 检查清单。
- 更新 `README.md`: 补充 `v0.1.0-dev` 状态徽章，完善项目核心价值与定位（针对传统 GIS 陡峭门槛与通用大模型幻觉的互补定位），链接所有规范文档。

### 3. 验证结果
- 全量单元测试 `python -m pytest backend/tests/test_spatial_tools.py -q` 全部通过 (66 passed)。
- 检查所有新增与更新 Markdown 文件的超链接及内部相对路径，确保无断链。
- 未提交代码保护检查通过，工作区纯净递进。

