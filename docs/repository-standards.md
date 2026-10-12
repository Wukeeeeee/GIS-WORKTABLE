# 命名与描述规范

这些约定适用于后续新增和修改的内容。已有公共接口与文件名按需迁移，避免为了统一外观造成兼容性破坏；外部工具生成的分支可保留其命名。

## 项目名称和仓库信息

| 场景 | 约定 | 示例 |
| --- | --- | --- |
| 面向用户的项目名 | `GIS WorkTable` | README 标题、介绍与演示材料 |
| GitHub 仓库标识 | 保留现有地址 | `Wukeeeeee/GIS-WORKTABLE` |
| 包名与机器标识 | 小写短横线 | `gis-worktable-desktop` |
| Git 分支 | `类型/简短英文主题` | `feat/layer-export`、`fix/utm-zone-boundary` |
| Codex 创建的分支 | 保留 `codex/` 前缀 | `codex/readme-and-contributing` |
| 发布标签 | `vMAJOR.MINOR.PATCH` | `v0.1.0`（格式示例，不代表已有发布） |

不要仅为显示名统一重命名仓库、工具 ID 或 API 路径。

推荐 GitHub About / Description：

> 开源 GIS 工作台：结合自然语言 AI Agent 与手动工具，支持空间数据处理、分析及 2D/3D 地图可视化。

英文版本：

> Open-source GIS workbench combining natural-language AI agents and manual tools for geospatial processing, analysis, and 2D/3D visualization.

Description 用一至两句说明“是什么、解决什么问题、主要方式”，不堆版本号、动态数量、获奖预期或“最强/全自动/百分百准确”等无法核验的措辞。

推荐 Topics：`gis`、`geospatial`、`spatial-analysis`、`ai-agent`、`langgraph`、`fastapi`、`leaflet`、`cesium`、`mcp`。这些是建议值，本次文档修改不会自动同步 GitHub About。

## 文件和代码命名

| 对象 | 约定 | 示例 |
| --- | --- | --- |
| 根目录社区文档 | 通用大写名称 | `README.md`、`CONTRIBUTING.md`、`CHANGELOG.md` |
| 新文档文件 | 小写短横线 | `release-guide.md` |
| Python 模块、函数、变量 | `snake_case` | `geo_coords.py`、`get_db_path` |
| Python 类 | `PascalCase` | `LLMConfig` |
| JavaScript 模块文件 | 延续现有 `snake_case.js` | `gis_state.js`、`raster_tools.js` |
| JavaScript 函数、变量 | `camelCase` | `renameLayer`、`layerId` |
| 常量、环境变量 | `UPPER_SNAKE_CASE` | `GEOSOURCE_DB_PATH` |
| GIS 工具 ID、JSON 字段 | 延续协议的 `snake_case` | `spatial_buffer`、`layer_name` |
| CSS 类 | 小写短横线，沿用模块前缀 | `layer-item` |
| pytest 文件、函数 | `test_*.py`、`test_*` | `test_geo_coords.py` |

跨边界字段按已有协议保留；JavaScript 局部变量与 JSON 字段不必强行同名。命名应说明领域含义，距离、面积和时间参数明确单位；避免没有上下文的 `data2`、`temp_new`、`final_v3`。

缩进与换行以根目录 `.editorconfig` 为准：UTF-8、LF，Python 四空格，其他文件两空格。修改旧文件时沿用局部风格，避免无关格式化。

## Commit 规范与 Description（提交说明）

采用 Conventional Commits 风格，**纯中文、重点清晰、杜绝双语冗余与八股文**。

> **术语约定**：开发中所述的 **Description** 均指 **Git Commit 的详细描述（Message Body）**，而非 PR 描述。

### 1. 提交标题（Commit Title）

```text
type(scope): 简短精炼的核心改动总结
```

- **类型 (type)**：`feat`（新功能）、`fix`（缺陷修复）、`refactor`（代码重构）、`perf`（性能提升）、`test`（测试用例）、`docs`（文档更新）、`chore`（构建/工具链/维护）。
- **范围 (scope)**：`core`、`agent`、`tools`、`layers`、`map`、`viz`、`project`、`ui` 等。
- 建议控制在约 50~72 字符内，一眼看出核心变更。

### 2. 提交说明（Commit Description）

针对多模块或跨系统更新，在第一行 Title 后空一行，正文中**按模块划分小节**（格式为 `type(sub-scope): 中文小结`），并在下方列出 1~3 条核心改动要点：

```text
feat(core): 核心体验升级——图层感知增强、工作区交互完善与出图字体修复

feat(layers): 优化图层属性表与拖拽排序
- 属性表增行与保存后保持当前激活标签页，新增“+列”自定义字段与字段计算器
- 增加图层拖拽放置指示线（上下高亮线）与卡片幽灵拖动样式

feat(map): 增加缩放范围控制与透明度联动
- 参照 ArcMap 增加图层可见缩放范围（min/max zoom），随地图缩放自适应显隐
- 打通图层卡片与属性检查器透明度滑块的双向联动，支持手绘要素透明度调节

feat(agent): 增强图层状态感知与路由稳定性
- 扩展 get_registered_layers 返回要素数、几何类型、bbox与属性字段
- 优化意图路由与提示词，避免图层查询被跳过，禁止图层存在时回复免责声明

feat(viz): 修复 Matplotlib 中文字体方块乱码
- 调整沙箱样式加载顺序，解决中文标签显示为方块（□□□）的问题
- 完善专题图布局提示，防止图例表格与主图重叠

feat(project): 彻底修复新建工程残留图层底图问题
- 新建工程与重置会话时深度清理 GIS.state 与孤立图层，消除幽灵边界残留

test(core): 补充图层感知工具回归测试
- 补充针对新版 get_registered_layers 与 list_layers 的单元测试（15 passed）
```

### 3. 本地 Git 模板启用

在项目根目录下已配置 `.gitmessage` 模板，可在本地终端执行以下命令将该模板绑定为本地默认提交模板：

```bash
git config --local commit.template .gitmessage
```



## Issue、PR 与功能描述

Issue 标题描述可观察现象：`切换到 3D 后隐藏图层重新出现`。正文给出环境、输入、步骤、实际结果和预期结果；功能建议说明用户场景和验收条件。

PR 标题沿用提交格式；Description 先写触发问题和改后行为，再写必要的实现依据、验证与兼容性。使用仓库 PR 模板，不将聊天记录或未运行的测试当作证据。

功能文档明确区分“代码已实现”“已在某环境验证”“计划支持”。写出依赖网络、账号、CRS、输入格式等使用条件；AI 自动调用、后端工具和手动 UI 是不同入口，分别描述实际支持情况。

## 更新记录

面向用户的变化加入 [CHANGELOG](../CHANGELOG.md) 的 `[Unreleased]`，按 Added / Changed / Fixed / Deprecated / Removed / Security 分类，只保留实际有内容的分类。记录用户可见行为及限制，不简单复制提交列表。

工具数、数据源数、覆盖率和性能指标如需公开，必须附统计口径、日期、代码提交或数据库快照、执行命令。发布与版本规则见 [发布流程](release-guide.md)。
