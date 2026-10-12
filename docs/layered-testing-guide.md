# GIS-WorkTable 分层测试体系指南 (Layered Testing Guide)

## 一、核心原则：真实依赖，拒绝割裂

本系统的 AI Agent 与 GIS 工具、地图图层管理、前后端接口存在真实依赖。
**严禁为了追求“模块独立”而将 AI Core 强行改造成脱离 GIS 运行环境的孤立模块。**

分层测试的核心目的是：**在保留 GIS-WorkTable 真实运行链路的前提下，让 AI 相关功能能够逐层定位问题，并通过完整集成测试确保修改没有破坏地图业务。**

---

## 二、五层分层测试架构

| 层级 | 测试范围 | 真实依赖 vs Mock | 典型验证场景 | 运行耗时 |
| :--- | :--- | :--- | :--- | :--- |
| **Layer 1: 单元测试**<br>`test_layer1_unit.py` | Prompt 组装、上下文解析、参数校验、Result Guard 守卫 | **Mock 外部模型与网络**，纯 Python 逻辑 | 提示词红线检查、免责声明与未执行代码拦截函数、上下文提取机制 | < 1s |
| **Layer 2: Agent 测试**<br>`test_layer2_agent.py` | 意图识别、工具选择、上下文复用、追问拦截 | **复用真实生产 LangGraph Agent**，输入确定性模拟响应 | 多轮重名区县自动消歧、严禁方案A/B过度追问、拦截未执行免责代码 | < 2s |
| **Layer 3: GIS 工具集成测试**<br>`test_layer3_gis_tools.py` | 空间计算、真实矢量获取、真实 Matplotlib 制图 | **使用真实 GIS 算法与受控数据** | DataV 真实行政边界格式、execute_python 实际产出有效 PNG 图片、单要素优雅降级 | < 5s |
| **Layer 4: 地图集成测试**<br>`test_layer4_map_integration.py` | 图层注册机制、状态同步、FastAPI 图层接口、GeoJSON 合规性 | **真实前后端数据模型**，验证 Leaflet/VectorGrid 消费能力 | `_register_layer` 状态挂载、`/api/layer/list` 序列化、坐标在有效经纬度范围 | < 3s |
| **Layer 5: 端到端业务测试**<br>`test_layer5_e2e.py` | 完整闭环业务流程：输入 → Agent → 工具 → 图层注册 → 交付 | **全链路集成** | 通过接口调度工具链完成图层上图与成果图片生成，流式 SSE 事件交付 | < 6s |

---

## 三、三种执行模式与运行指令

项目提供统一的分层测试入口脚本 `scripts/run_layered_tests.py`，支持按需分组执行：

### 1. 快速模式 (Fast Mode)
适合日常迭代、代码小修、Prompt 微调。
```bash
python scripts/run_layered_tests.py --mode fast
# 或使用 pytest marker:
pytest backend/tests/layered/ -m "fast" -v
```
- **覆盖层级**：Layer 1 (单元测试) + Layer 2 (Agent 测试)
- **执行时间**：~2 秒

### 2. 集成模式 (Integration Mode)
适合修改了 GIS 空间工具、图层状态、数据源代理或图层接口后运行。
```bash
python scripts/run_layered_tests.py --mode integration
# 或使用 pytest marker:
pytest backend/tests/layered/ -m "integration" -v
```
- **覆盖层级**：Layer 3 (GIS 工具集成) + Layer 4 (地图图层集成)
- **执行时间**：~6 秒

### 3. 全量回归模式 (Regression Mode)
适合功能合并、交付前全面验收。
```bash
python scripts/run_layered_tests.py --mode regression
# 或运行全部 5 层:
python scripts/run_layered_tests.py --mode all
```
- **覆盖层级**：全部 5 层测试，确保从提示词、Agent 决策、空间计算到图层注册与成果落盘无任何断点。

---

## 四、研发守则与测试触发矩阵

1. **修改 Prompt 或 Agent 逻辑时**：
   - 必须执行：`python scripts/run_layered_tests.py --layer 1` 与 `python scripts/run_layered_tests.py --layer 2`；
   - 必须确认：没有引入新的过度追问，且未破坏上下文实体继承。
2. **涉及 GIS 工具、图层流程或数据源时**：
   - 必须执行：`python scripts/run_layered_tests.py --mode integration`；
   - 必须确认：产出的 GeoJSON 和图片文件在磁盘与全局状态中均有效。
3. **真实环境声明准则**：
   - 只有在完整执行并通过 Layer 5 端到端测试后，才能声称端到端业务已验证；
   - 当未配置外部商业 API Key 时，明确说明处于 Mock 闭环测试状态。
