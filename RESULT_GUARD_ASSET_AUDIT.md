# RESULT\_GUARD\_ASSET\_AUDIT.md

> 技术尽调报告：GIS-WorkTable 的 
>
> `result_guard`
>
>  是否值得独立开源
> 尽调日期：2026-09-19
> 尽调人身份：技术尽调（非开发者，不修改任何代码）
> 原则：不为证明它有价值而找理由；证明不了就说不值得



***

## 一、当前实现概述

### 1.1 文件清单



| 文件                                    | 行数                    | 职责                          |
| ------------------------------------- | --------------------- | --------------------------- |
| `backend/services/result_guard.py`    | 207 行                 | 本审计对象：事后确定性校验               |
| `backend/tests/test_result_guard.py`  | 170 行                 | 测试                          |
| `backend/services/graph.py` 行 477、720 | 2 处调用                 | 流式 / 非流式入口                  |
| `backend/services/pending_action.py`  | —                     | pending 状态来源                |
| `backend/services/tools.py` 行 189     | `get_pending_state()` | pending 结构定义                |
| `backend/services/task_manager.py`    | —                     | **隐藏价值**：artifact 注册表（见第八节） |

### 1.2 result\_guard.py 的实际代码结构



```
result\_guard.py

├── \_PROJECT\_ROOT            # 硬编码：本文件上三级

├── \_OUTPUT\_DIRS             # 硬编码：output/cache/uploads/reports/data 六个目录映射

├── \_RECOGNIZED\_EXTS         # 硬编码：23 种文件后缀

├── \_PATH\_RE                 # 正则：从文本提取路径

├── extract\_output\_paths()   # 正则提取（去重保序）

├── resolve\_artifact\_path()  # 相对路径 → 绝对路径

├── verify\_result()          # 核心校验（三项检查）

├── build\_guard\_note()       # 生成追加提示文本

└── apply\_guard()            # 入口：校验 + 追加到回复末尾
```

### 1.3 依赖

纯 Python 标准库：`os`、`re`、`tempfile`。**无第三方依赖**。



***

## 二、完整调用链（以代码为准）



```
用户消息

&#x20; ↓

graph.py: run\_agent() / run\_agent\_stream()

&#x20; ↓

LangGraph ReAct 循环（工具调用、多轮推理）

&#x20; ↓

final\_text = \_last\_ai\_text(messages)          # 从最后一条 AI 消息提取文本

pending = get\_pending\_state()                 # 从 tools.py 获取待推送状态

&#x20; ↓

graph.py:477 / graph.py:720

&#x20; final\_text, \_guard = result\_guard.apply\_guard(final\_text, pending)

&#x20; ↓

verify\_result(final\_text, pending):

&#x20; ① 正则提取 final\_text 中的 output/cache/uploads/reports/data 路径

&#x20;    → os.path.isfile() and os.path.getsize() > 0

&#x20; ② pending.images 中 url 以 "/" 开头的

&#x20;    → resolve\_artifact\_path → os.path.isfile() and size>0

&#x20; ③ pending.layers 中 geojson 为空的

&#x20;    → 报告 empty\_layers

&#x20; ↓

build\_guard\_note(\_guard)

&#x20; → 生成 "【结果真实性自检】以下内容未通过..." 提示文本

&#x20; ↓

final\_text += note（追加到回复末尾，不修改、不拦截、不重试）

&#x20; ↓

返回前端：

&#x20; response = final\_text（已被追加提示）

&#x20; result\_check = \_guard（校验详情，前端展示）
```

**关键架构事实**：



* result\_guard 是**事后展示性校验**，不是事前拦截

* 它不阻止 Agent 的 "完成" 宣称，只是把问题**追加**到回复末尾

* 它不做重试，不触发工具重新执行

* 历史的 `_run_verifier`（LLM 自校验）已于 2026-09-05 停用，原因见 graph.py:466-472 注释："每轮额外一次 LLM 调用，增加延迟和 API 成本；实际运行中极少抓到错误（大量默认通过的兜底逻辑导致放行率高）"



***

## 三、已实现能力（代码证据）

### 3.1 已实现



| 能力                 | 代码位置                                | 证据                                                           |
| ------------------ | ----------------------------------- | ------------------------------------------------------------ |
| 从 LLM 回复文本正则提取文件路径 | result\_guard.py:57-62 `_PATH_RE`   | 正则匹配 `dir/rest.ext`，支持中文文件名、目录层级                             |
| 核对文件存在             | result\_guard.py:133                | `os.path.isfile(abs_path) and os.path.getsize(abs_path) > 0` |
| 核对空文件              | result\_guard.py:133                | size>0 判断（0 字节视为未生成）                                         |
| 核对待推送图片文件          | result\_guard.py:141-159            | pending.images 的 URL → resolve → isfile                      |
| 核对图层 GeoJSON 非空    | result\_guard.py:162-168            | pending.layers 的 geojson 字段判断                                |
| 生成追加提示             | result\_guard.py:187-206            | `build_guard_note` 拼接中文提示                                    |
| 只报 "确定出问题" 项       | result\_guard.py:23 注释              | 做不到确定结论的一律不报                                                 |
| 问题数量上限保护           | result\_guard.py:64 `_MAX_ISSUES=5` | 防刷屏                                                          |

### 3.2 未实现（用户审计清单逐项对照）



| 用户要求的检查步骤          | 是否实现      | 证据                                                |
| ------------------ | --------- | ------------------------------------------------- |
| 是否存在               | ✅ 已实现     | isfile                                            |
| 是不是文件              | ✅ 已实现     | isfile                                            |
| 是否可以读取             | ❌ **未实现** | 代码无 open ()、无读取测试                                 |
| 格式是否正确             | ❌ **未实现** | 无 JSON 解析、无 PNG 头、无 CSV 列数、无 Shapefile 结构         |
| 内容是否为空             | ⚠️ 部分     | 仅 size>0；GeoJSON 仅判断 geojson 字段非空，不检查 features 数量 |
| 是否满足最基本数据要求        | ❌ **未实现** | 无坐标范围、无投影、无行数、无数值范围检查                             |
| 是否允许 Agent 宣称 "完成" | ❌ **未实现** | 不修改 Agent 判断，只追加提示；不触发重试                          |

### 3.3 隐藏的未实现项



| 项                                     | 证据                                                                                                          |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| 重试机制                                  | graph.py 有 LLM API 重试（空响应 / TypeError / 网络异常），但**不是 artifact 层面的重试**                                        |
| 失败 artifact 恢复                        | 无。校验失败后只是追加文本，不重新执行工具                                                                                       |
| execution audit                       | task\_manager 有 exec\_log，但 result\_guard **完全不使用它**（见 get\_pending\_state 返回的 exec\_log，verify\_result 不读） |
| 与 task\_manager.register\_artifact 联动 | **完全脱节**。task\_manager 有 artifact 注册表（见第八节），result\_guard 不查它，只查磁盘                                          |



***

## 四、通用 vs GIS 特有拆分

### 4.1 完全可以脱离 GIS-WorkTable 的部分



| 代码                            | 通用度   | 说明                         |
| ----------------------------- | ----- | -------------------------- |
| `_PATH_RE` 正则提取路径             | ⭐⭐⭐⭐⭐ | 纯文本处理，与 GIS 无关             |
| `extract_output_paths()`      | ⭐⭐⭐⭐⭐ | 同上                         |
| `os.path.isfile() and size>0` | ⭐⭐⭐⭐⭐ | 通用文件存在性                    |
| `build_guard_note()`          | ⭐⭐⭐⭐  | 文本拼接，语言可换                  |
| `resolve_artifact_path()`     | ⭐⭐⭐   | 逻辑通用，但依赖 \_OUTPUT\_DIRS 配置 |

### 4.2 依赖 GIS-WorkTable 架构的部分



| 代码                       | 耦合点                                               | 抽离难度             |
| ------------------------ | ------------------------------------------------- | ---------------- |
| `_OUTPUT_DIRS` 硬编码       | 假设 output→tempdir、cache/uploads/reports/data→项目根  | 需参数化（构造器 / 配置）   |
| `pending.images` 检查      | GIS-WorkTable 特有的 `_pending_images` 列表            | 需抽象为 "额外声明清单"    |
| `pending.layers` 检查      | GIS-WorkTable 特有的 `_pending_layers`（geojson 字段）   | **GIS 特有**，抽离时应砍 |
| `get_pending_state()` 结构 | 依赖 tools.py 的 `_pending_layers`/`_pending_images` | 需重新定义输入接口        |

### 4.3 纯 GIS-WorkTable 业务逻辑



| 代码                              | 说明                |
| ------------------------------- | ----------------- |
| `pending.layers` 的 geojson 非空检查 | 仅服务于 GIS 图层推送     |
| 中文文件名正则 `[\u4e00-\u9fa5]`       | 通用（但恰好是中文 GIS 场景） |

### 4.4 抽离后的最小核心

如果抽离，最小核心是：



```
\# 理想的通用核心（当前代码的子集）

verify(text: str,

&#x20;      declared\_paths: list\[str],   # 额外声明清单（替代 pending）

&#x20;      output\_dirs: dict\[str, str]   # 目录映射（替代硬编码）

&#x20;      ) -> VerificationResult
```

砍掉 pending.layers（GIS 特有），保留 pending.images 抽象为 declared\_paths。



***

## 五、外部竞品（A/B/C/D 四类）

### 5.1 A 类：结构化输出校验（背景，非直接竞品）



| 项目                     | 解决问题                         | 与 result\_guard 关系     |
| ---------------------- | ---------------------------- | ---------------------- |
| Pydantic / Pydantic AI | LLM 输出 JSON Schema 是否合法      | 背景。校验 "格式对"，不校验 "文件存在" |
| Rynko Flow             | LangGraph 外部 schema + 业务规则校验 | 背景。校验 "数据对"，不校验 "文件存在" |

### 5.2 B 类：LLM Guardrails / Safety（背景，非直接竞品）



| 项目               | 解决问题                      | 与 result\_guard 关系                                 |
| ---------------- | ------------------------- | -------------------------------------------------- |
| Guardrails AI    | 对话内容安全 / 输出约束             | 背景。不做文件核对                                          |
| NeMo Guardrails  | 输入 / 对话 / 检索 / 输出安全 rails | 背景。tool-calling rail 校验 tool\_call\_id 一致性，不校验文件存在 |
| ignis-guardrails | LLM 二次调用校验输出与上下文一致性       | 背景。语义校验，不是磁盘核对                                     |

### 5.3 C 类：Tool / Agent execution validation（重要相关）



| 项目                                                | 解决问题                                                                                    | 与 result\_guard 重合                                           |
| ------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| **detent**（PyPI，Apache-2.0，2026-03，活跃，427+ tests） | **事前**拦截 AI coding agent 文件写入，跑验证管道（syntax/lint/typecheck/tests/security），失败原子回滚        | **低重合**。detent 做事前写入拦截 + 代码质量验证；result\_guard 做事后文件存在核对。方向不同 |
| **agentclaimguard**（PyPI，Apache-2.0，2026-06，52★）  | 结构化 claim vs evidence/tool-result/policy contract 的逻辑校验（如 "收入增长 15%" 是否有 calculator 证据） | **低重合**。做逻辑证据校验，不查文件系统                                       |
| agentverify（PyPI）                                 | LangGraph 步骤间数据传递断言（assert\_step\_uses\_result\_from）                                   | **低重合**。验证步骤间数据流，不验证文件                                       |
| bracket-harness（PyPI）                             | callback 观察 tool calls 为 canonical evidence（file reads/web fetches/shell）               | **中重合**。做 artifact 追踪，但偏向证据收集，不是 "事后核对文件存在"                  |
| halo-record（PyPI）                                 | 篡改证明的 agent 审计日志（append hash-chained log）                                               | **低重合**。审计追踪，不做存在性核对                                         |

### 5.4 D 类：Artifact verification（重点）



| 项目                                                                                                 | 解决问题                                                    | 与 result\_guard 重合                                         |
| -------------------------------------------------------------------------------------------------- | ------------------------------------------------------- | ---------------------------------------------------------- |
| **detent**（同上）                                                                                     | 事前拦截写入                                                  | **不同**：事前 vs 事后                                            |
| **agentclaimguard**（同上）                                                                            | 逻辑证据校验                                                  | **不同**：逻辑 vs 物理                                            |
| **DEV.to 文章："Build a Tiny Tool-Result Gatekeeper Before You Trust an Agent's 'Done'"**（2026-09-10） | 执行 tool call 后检查实际 side effect（文件系统），当模型声明与文件系统不一致时拒绝结果 | **最高重合**。但它是文章不是库；且做的是 "拒绝结果"，比 result\_guard 的 "追加提示" 更激进 |
| Google ADK Artifacts                                                                               | agent 生成 artifact 的 load/save API                       | **低重合**。文件管理 API，不是校验                                      |

### 5.5 关键结论

**在本次检索范围内，未发现与 result\_guard 高度重合的成熟开源项目。**



* detent 做事前代码验证，不做事后文件存在核对

* agentclaimguard 做逻辑证据校验，不查文件系统

* bracket-harness 做证据收集，不做存在性核对

* DEV.to 那篇文章描述了相同问题，但未发布为库

**但这不等于 "空白"**—— 见第七节 "为什么这不构成壁垒"。



***

## 六、技术壁垒评估（诚实回答）

### 6.1 它是不是仅仅 `os.path.exists(path)`？

**答：90% 是。**

代码证据：



```
\# result\_guard.py:133 核心逻辑

exists = os.path.isfile(abs\_path) and os.path.getsize(abs\_path) > 0
```

加上：



* 正则提取路径（\_PATH\_RE，约 5 行正则）

* pending.images/layers 的 GIS 特定检查（约 20 行）

* build\_guard\_note 文本拼接（约 20 行）

**没有任何算法、任何框架依赖、任何跨项目设计模式是 "别人写不出来" 的。**

### 6.2 它有没有形成完整机制？

**答：没有。**

用户要求的完整机制：



```
LLM claim → artifact extraction → deterministic verification → execution state → final response
```

GIS-WorkTable 的实际：



```
LLM claim（final\_text 文本）

&#x20; → artifact extraction（正则提取 \_PATH\_RE）

&#x20; → deterministic verification（isfile + size>0）

&#x20; → execution state（\*\*断裂\*\*：不查 task\_manager.register\_artifact，不读 exec\_log）

&#x20; → final response（追加提示，不修改、不拦截、不重试）
```

**execution state 这一环是断的。** result\_guard 不读 task\_manager 的 artifact 注册表，不读 exec\_log，不查工具实际执行了什么。它只做 "文本声称 vs 磁盘现状" 的静态对比。

### 6.3 是否具有跨 Agent / 跨框架复用价值？

**答：理论上可以，实际上太薄。**



* 可以用于 LangGraph / LangChain / OpenAI Agents / CrewAI / AutoGen—— 任何 "LLM 生成文件" 的 agent

* 但每个项目加 10 行代码（正则 + isfile + 追加）就能自己实现

* 没有复杂到需要 "引入一个库" 的程度

### 6.4 去掉 GIS 后核心是否仍然成立？

**答：成立，但只是一个很薄的 "路径提取 + isfile" 工具。**



***

## 七、为什么这不构成壁垒

### 7.1 问题真实，但解决方案太薄

LLM 幻觉 "已生成 xxx.png" 是真实问题。但：



* 解决方案是 5 行正则 + 2 行 isfile

* 任何做 LLM 文件生成的项目，开发者花 10 分钟就能自己写一个

* 没有 "必须用库" 的复杂度门槛

### 7.2 竞品在快速演进



* detent（2026-03 发布，v2.0 计划 2027 Q1）正在快速扩展 agent verification runtime

* agentclaimguard（2026-06 发布，活跃）正在扩展 claim 校验类型

* 这两个项目都可能很快覆盖 "事后文件核对" 这个角落

### 7.3 "事后核对" 这个方向的价值存疑



* detent 的路线是 "事前拦截"—— 更彻底，更受工程界欢迎

* agentclaimguard 的路线是 "逻辑证据"—— 更通用，不绑定文件

* result\_guard 的路线是 "事后文本核对"—— 最轻量，但也最容易被开发者自己写



***

## 八、隐藏价值（task\_manager.register\_artifact）

### 8.1 发现

task\_manager.py 行 370-404：



```
def register\_artifact(task\_id: str, filename: str, filepath: str, ...):

&#x20;   """登记 artifact 到任务记录"""

def get\_artifacts(task\_id: str) -> list: ...

def get\_artifact(task\_id: str, artifact\_id: str) -> Optional\[dict]: ...
```

这是一个**任务级 artifact 注册表**：



* 工具执行时主动登记（filename、filepath、metadata）

* 磁盘持久化 JSON（`_artifacts_json_path`）

* 支持查询、版本管理

### 8.2 但它与 result\_guard 脱节



* result\_guard 不查 task\_manager.register\_artifact 的登记表

* result\_guard 不读 get\_pending\_state 返回的 exec\_log

* 两者是平行机制，没有形成 "工具登记 → 回复声明 → 核对登记" 的闭环

### 8.3 如果整合，价值是什么

完整机制应该是：



```
工具执行 → register\_artifact(task\_id, filename, filepath)  # 事前登记

&#x20; ↓

LLM 回复 → "已生成 xxx.png"                                    # 声称

&#x20; ↓

result\_guard → 对比 LLM 声称 vs 登记表 vs 磁盘                # 核对

&#x20; ↓

不一致 → 追加提示 / 重试 / 拒绝"完成"                         # 处置
```

GIS-WorkTable 有这个雏形（register\_artifact 已存在），但 result\_guard 没有用上它。



***

## 九、独立开源后的最小 MVP（假设要做）

### 9.1 MVP 形态



```
\# 不是直接抽 result\_guard.py，而是重新设计

from artifact\_guard import ArtifactGuard

guard = ArtifactGuard(

&#x20;   output\_dirs={"output": "/app/output", "reports": "/app/reports"},

)

\# 工具执行时登记

guard.register("output/map.png", metadata={"type": "image"})

\# LLM 回复后核对

report = guard.verify(final\_text="已生成 output/map.png",

&#x20;                     declared\_paths=\["output/map.png"])

\# report.missing / report.ok / report.issues
```

### 9.2 与 detent /agentclaimguard 的差异化



| 维度       | detent                        | agentclaimguard             | 本 MVP            |
| -------- | ----------------------------- | --------------------------- | ---------------- |
| 时机       | 事前拦截                          | 逻辑校验                        | **事后文件核对**       |
| 检查对象     | 代码质量                          | 逻辑证据                        | **物理文件存在**       |
| 是否依赖 LLM | 否                             | 否                           | 否                |
| 是否绑定框架   | Claude Code/Codex/Gemini hook | LangGraph/LangChain adapter | **框架无关**         |
| 处置方式     | 回滚                            | 阻断 / 路由                     | **追加提示 / 标记未完成** |

### 9.3 潜在用户



* 做 "LLM 生成报告 / 图表 / 数据文件" 类 agent 的开发者

* 需要 "前端真的能加载 agent 声称的文件" 的场景

* 不想引入 detent 的重验证管道，也不需要 agentclaimguard 的逻辑校验

### 9.4 为什么他们不用现有方案



* detent：太重（syntax/lint/typecheck/tests/security 全套管道），面向 coding agent

* agentclaimguard：不查文件，只查逻辑证据

* 自己写：10 行代码能写，但需要处理正则提取、目录配置、提示文本、边界情况 —— 这就是库的价值

### 9.5 开源风险



| 风险       | 说明                                 |
| -------- | ---------------------------------- |
| **太薄**   | 核心就是 isfile，可能被视为 "不值得引入的库"        |
| **竞品挤压** | detent/agentclaimguard 快速演进，可能很快覆盖 |
| **受众窄**  | 只有 "LLM 生成文件" 类项目需要，不是通用 agent 需求  |
| **维护成本** | 需要维护正则、目录配置、多格式校验，否则很快过时           |



***

## 十、最终建议

### 选项



* A. 立即抽离

* B. 值得抽离，但需要重新设计

* C. 暂时保留在 GIS-WorkTable

* D. 不建议继续投入

### 建议：**B. 值得抽离，但需要重新设计**

### 理由



1. **当前 result\_guard.py 直接抽出来不值得**—— 它就是 5 行正则 + 2 行 isfile，是 "os.path.exists 包装"（代码证据：result\_guard.py:133）

2. **但它背后的问题（LLM 幻觉声称文件已生成）是真实的**，且现有竞品（detent 事前、agentclaimguard 逻辑）没有覆盖 "事后文件核对" 这个角落

3. **task\_manager.register\_artifact 是隐藏价值**—— 如果把它和 result\_guard 整合成 "工具登记 → LLM 声称 → 三方核对（登记表 / 磁盘 / 文本）" 的闭环，就不是 "os.path.exists 包装" 了

4. **重新设计的方向**：

* 砍掉 pending.layers（GIS 特有）

* 把 \_OUTPUT\_DIRS 参数化

* 接入 register\_artifact 作为 "事前登记" 源

* 增加格式校验（至少 JSON 解析、PNG 头）

* 增加 "是否允许宣称完成" 的最终判定（不只是追加提示）

1. **但要诚实**：这个方向的受众窄（只有文件生成类 agent 需要），且 detent 可能很快覆盖。如果做，定位必须明确是 "轻量、事后、文件核对"，不要和 detent 正面竞争

### 不建议 A 的理由

当前 207 行代码直接抽出来，就是 os.path.exists 包装，没有独立价值。

### 不建议 C 的理由

问题真实（LLM 幻觉文件），且 task\_manager.register\_artifact 的雏形已存在，整合成本低。

### 不建议 D 的理由

问题真实存在，且本次检索未发现直接竞品完全覆盖。



***

## 十一、数据来源声明



* **代码证据**：E:\my\_repo\Gis-WorkTable\backend\services\result\_guard.py（207 行）、graph.py:477/720、tools.py:189、task\_manager.py:370-404、test\_result\_guard.py（170 行）

* **外部竞品**：PyPI 页面（agentclaimguard 0.4.3、detent 1.2.0、agentverify、bracket-harness、halo-record）、DEV.to 文章（2026-09-10 "Build a Tiny Tool-Result Gatekeeper"）、Guardrails AI / NeMo Guardrails 官方文档

* **未确认项**：


  * detent/agentclaimguard 的完整 GitHub 源码（仅基于 PyPI 描述和 README）

  * DEV.to 文章的代码是否已发布为库（仅文章，无 PyPI 包）

  * 其他 GitHub 小项目未逐个排查