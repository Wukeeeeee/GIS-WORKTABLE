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

## Commit 与 PR 标题

采用 Conventional Commits 风格：

```text
type(scope): 中文描述 / English description
```

类型：`feat` 新能力、`fix` 修复、`docs` 文档、`refactor` 不改变外部行为的重构、`test` 测试、`perf` 性能、`build` 依赖/构建、`ci` 自动化、`chore` 维护、`revert` 回退。

scope 推荐：`agent`、`tools`、`map`、`layers`、`3d`、`geosource`、`mcp`、`desktop`、`docs`。可按模块新增，scope 可以省略。

提交标题和正文使用中英双语，中文在前、英文在后。`type` 与 `scope` 保留英文机器标识；两种语言描述同一组具体变化，避免英文部分额外增加功能承诺。

```text
fix(tools): 限制 UTM 带号 / Clamp UTM zones
feat(layers): 导出选中图层 / Export selected layers
docs: 补充贡献指南 / Add contribution guide
```

标题建议控制在约 72 字符内。说明改了什么，避免只写 `update`、`优化`、`修复 bug`。正文先用中文描述具体改动，再给出对应英文；提交说明不包含验证结果或限制章节，验证证据仍记录在相关文档或 PR 中。破坏兼容时使用 `!`，并在正文写 `BREAKING CHANGE:` 和迁移办法。

已推送的历史默认保留，不为套用规范批量改写。维护者明确要求修正某条已推送提交时，应先保留原提交的恢复引用，核对远程提交，并使用 `--force-with-lease` 防止覆盖其他人的新增提交。

## Issue、PR 与功能描述

Issue 标题描述可观察现象：`切换到 3D 后隐藏图层重新出现`。正文给出环境、输入、步骤、实际结果和预期结果；功能建议说明用户场景和验收条件。

PR 标题沿用提交格式；Description 先写触发问题和改后行为，再写必要的实现依据、验证与兼容性。使用仓库 PR 模板，不将聊天记录或未运行的测试当作证据。

功能文档明确区分“代码已实现”“已在某环境验证”“计划支持”。写出依赖网络、账号、CRS、输入格式等使用条件；AI 自动调用、后端工具和手动 UI 是不同入口，分别描述实际支持情况。

## 更新记录

面向用户的变化加入 [CHANGELOG](../CHANGELOG.md) 的 `[Unreleased]`，按 Added / Changed / Fixed / Deprecated / Removed / Security 分类，只保留实际有内容的分类。记录用户可见行为及限制，不简单复制提交列表。

工具数、数据源数、覆盖率和性能指标如需公开，必须附统计口径、日期、代码提交或数据库快照、执行命令。发布与版本规则见 [发布流程](release-guide.md)。
