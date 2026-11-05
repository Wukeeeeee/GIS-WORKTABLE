# DataV 行政区代码查询缺陷交接与独立审查

## 范围与结果

- 项目：`E:\my_repo\Gis-WorkTable`
- 检查范围：`backend/services/datav_service.py` 的 `_find_adcode` 查询优先级与回归测试。
- 分工与归属：
  - **GPT 实施**：重构 `_find_adcode` 查找优先级，修复省名子串回退抢在城市字典之前导致的错码缺陷；新增针对性回归套件 `backend/tests/test_datav_service.py`。
  - **Gemini 独立审查与验证**：在 Antigravity 会话中完成独立代码审计、行为逻辑推演、测试重跑（2/2 passed）及工作区干净度检查。
- 结论：实现精准、最小化且向后兼容，确认验收通过。

## 缺陷根因与修复决策

1. **缺陷根因**：
   - 修复前 `_find_adcode` 中，步骤 2 先截取 `['省', '市', '区', '县', ...]` 后缀，并执行 `if bare in k`（`k` 为省级字典 `_ADCODES` 的键）。
   - 当输入 `吉林市` 时，截取 `'市'` 得 `bare = '吉林'`，触发 `'吉林' in '吉林省'`，直接错误返回省级代码 `220000`，使后续城市字典 `city_map` 完全失效。这会导致下钻时错误获取全省地市而非该市下属区县。
   - 类似地，任何未知的区县/城市名称若包含省名子串，也会被错误泛匹配提升到省级代码。
2. **修复决策**：
   - 维持同名区县消歧（`_AMBIGUOUS_DISTRICTS`）与省级全称精确匹配（`clean_name in _ADCODES`）的高优先级不变。
   - 将城市字典（`_load_city_adcodes`）查询及其常规后缀变体检查调整至省名子串回退之前。
   - 对带有 `('省', '市', '区', '县', '自治州', '自治区', '特别行政区')` 后缀但未在城市字典命中的未知行政区，直接返回 `0`，杜绝因子串泛匹配产生的假阳性误判。

## 验证与测试结果

1. **测试执行**：
   ```powershell
   D:\python\python.exe -m pytest -q backend/tests/test_datav_service.py -p no:cacheprovider --tb=short
   ```
   **结果**：`2 passed in 0.04s`。
   - `test_find_adcode_prefers_exact_city_over_province_substring`：验证 `吉林市 -> 220200`、`吉林省 -> 220000`。
   - `test_find_adcode_does_not_guess_province_for_unknown_city`：验证 `吉林新区市 -> 0`，不误猜省份。

2. **代码风格与差异检查**：
   ```powershell
   git diff --check -- backend/services/datav_service.py backend/tests/test_datav_service.py docs/validation/datav-service-handoff.md
   ```
   **结果**：退出码 0，无任何多余空白或格式冲突。

## 假设与未解决限制

1. **无外部网络依赖**：测试完全使用 mock 隔离 `_load_city_adcodes`，未产生任何外网 DataV 请求。
2. **审计范围边界**：本轮审查严格限定在 `_find_adcode` 查询优先级与回归；`fetch_boundary` 与 `fetch_boundary_by_adcode` 的完整网络超时重试与全量资产端到端流转保留在后续审计阶段。
3. **工作区保护**：除所有权文件 `backend/services/datav_service.py`、`backend/tests/test_datav_service.py` 及本文档外，工作区已有未提交改动完全未被触碰。
4. **Context Meter**：界面未显示上下文用量/剩余量数值（标注为未显示）。
