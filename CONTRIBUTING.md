# 贡献指南

欢迎提交可复现的问题、文档修正、GIS 工具改进和测试。开始前请阅读 [README](README.md) 与 [命名和描述规范](docs/repository-standards.md)。

## 开发流程

1. 按 README 创建虚拟环境、安装依赖并启动项目。
2. 修改前检查 `git status`，保留已有工作区改动。较大功能或接口变更先开 Issue 说明场景和设计。
3. 从项目默认分支创建工作分支；外部贡献者先 Fork。命名示例：`feat/layer-export`、`fix/utm-zone-boundary`。
4. 保持修改范围明确；不要将批量格式化、无关重命名和功能改动混入同一 PR。
5. 运行与修改对应的检查，更新文档及 `CHANGELOG.md` 的 `[Unreleased]` 条目，再提交 PR。

本仓库不要求为纯文档改动新增实现镜像测试。文档需检查路径、命令、链接和事实；行为修改应提供能检出回归的测试。

## 新增或修改 GIS 工具

1. 在 `backend/services/tools.py` 添加或调整 `@tool` 函数，并纳入 `tools` 注册表。
2. docstring 说明适用场景、参数、单位、坐标系、输入限制、输出和失败条件。改变已有名称或参数时评估 Agent、手动调用与 MCP 的兼容性。
3. 图层产物沿用 `_push_layer` / `_register_layer` 通道；避免绕开统一注册和结果检查机制。
4. 增加对应测试，覆盖正常路径及相关边界，例如空数据、无效几何、CRS、单位和经度边界。
5. 前端状态通过共享状态模块更新，核对 2D/3D 图层同步。仅新增后端工具不能宣称已有完整手动 UI。

## 验证

在仓库根目录执行，定向测试按实际修改选择：

```bash
python -m pytest backend/tests/test_spatial_tools.py -q
python -m pytest backend/tests/test_tool_registry.py -q
python -m pytest backend/tests/ -q
git diff --check
```

上面的空间分析测试仅是示例。行为修改在定向检查通过后运行全量后端测试；无法运行时，在 PR 明确原因，不能写成“全部通过”。涉及前端时记录浏览器、操作步骤、2D/3D 验证结果，必要时附脱敏截图。

## Issue 与 PR

- Bug：环境、复现步骤、预期行为、实际行为、最小数据与日志。
- 功能建议：具体用户问题、使用场景、可验收结果及依赖条件。
- PR：问题及原因、改后行为、验证命令与结果、兼容性影响、关联 Issue。
- 外部服务失败应区分网络、权限、数据源状态与代码错误；坐标问题请提供 CRS 和单位。

不提交 API Key、账号密码、浏览器 localStorage、个人对话历史或无分发授权的数据。交流时围绕可复现事实和方案讨论，尊重不同意见。

提交贡献时请确认有权按项目 [AGPL v3 许可证](LICENSE) 提供相应内容。第三方代码和数据需保留适用的来源与许可证说明。
