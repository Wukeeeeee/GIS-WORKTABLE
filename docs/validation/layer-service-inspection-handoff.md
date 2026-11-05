# 图层检测服务（layer_service）几何有效性缺陷修复与独立交接

## 1. 范围与所有权

- **仓库路径**：`E:\my_repo\Gis-WorkTable`
- **任务目标**：GIS WorkTable 发布就绪度（Release-readiness）目标下的图层元数据检测（`inspect_geojson`）质量验证与坐标健全性加固。
- **所有权文件（Own only）**：
  1. `backend/services/layer_service.py`（最小化修复实现）
  2. `backend/tests/test_layer_service.py`（针对性回归测试）
  3. `docs/validation/layer-service-inspection-handoff.md`（本交接文档）
- **非所有权边界与工作区保护**：
  - 确认并保护工作区中既有未提交改动（包括 `datav_service.py`、`project_service.py`、`sql_engine.py`、`tools.py`、`workflow.py` 及其对应测试与文档）。
  - 未引入任何外部网络调用、未引入新依赖包、未执行 git commit、未变更前端代码。

---

## 2. 缺陷复现、行为核验与影响判定

### 2.1 候选现象与复现确认
在原代码中输入以下候选要素时：
```python
inspect_geojson({"type": "Feature", "geometry": {"type": "Point", "coordinates": [True, 30]}, "properties": {}})
inspect_geojson({"type": "Feature", "geometry": {"type": "Point", "coordinates": ["100", "30"]}, "properties": {}})
```
原实现均返回 `invalid_geom_count: 0` 和 `null_geom_count: 0`，同时 `coord_sample: []`、`bbox: None`。

### 2.2 根因分析
1. **Shapely / GEOS 类型宽容隐式转换**：
   Python 中 `bool` 是 `int` 的子类（`isinstance(True, int) == True`）。当 `shapely.geometry.shape(geom)` 构造几何时，底层 GEOS / NumPy 将 Python 布尔值 `True` 强转为数值 `1.0`，将字符串数字 `"100"` 隐式转为浮点数 `100.0`，因而 `s.is_valid` 均返回 `True`。
2. **坐标提取与几何检测脱节**：
   `_extract_coords` 中已显式过滤了非 `Real` 及布尔值（`isinstance(..., Real) and not isinstance(..., bool)`），导致无效坐标点在提取时被静默跳过；但几何检验阶段完全委托给 Shapely，未能识别此类非数值坐标，最终导致 `invalid_geom_count` 漏报为 `0`。

### 2.3 契约规范与发布影响评估
1. **RFC 7946 GeoJSON 规范契约**：
   - 依据 RFC 7946 §3.1.1，GeoJSON 的 Position 必须是由两个或两个以上数值（Numbers）构成的数组，禁止使用 JSON 布尔值（`true`/`false`）或字符串。
   - 报告 `invalid_geom_count = 0` 会对下游空间计算（PostGIS、GDAL、Turf、Deck.gl 等）以及数据体检 API 调用方形成质量误导，属于**后端 API 正确性与契约缺陷**。
2. **前端与发布路径影响界定**：
   - 审查 `frontend/js/layers.js:1682` 发现：`var invalidCount = remote.invalid_geom_count !== undefined ? remote.invalid_geom_count : '未检测';` 仅赋值给局部变量 `invalidCount`，当前前端图层体检面板实际渲染的是本地快检的 `audit.nullGeometryCount`，未直接展示 `remote.invalid_geom_count`。
   - 结论：该缺陷属于**后端服务契约正确性缺陷**，尚未阻塞当前前端可见用户流；严格聚焦后端修复，不随意扩散至前端。

### 2.4 RFC 细微语义与边界决策
- **Geometry 坐标根数组 vs 空几何**：
  Geometry 对象的 `coordinates` 成员必须为数组。根坐标数组为空 `coordinates: []`（以及 `GeometryCollection` 的 `geometries: []`）是合法的空几何（Empty Geometry），必须保留为非无效（`invalid_geom_count = 0`, `null_geom_count = 0`）。
- **坐标成员为 null**：
  Geometry 对象如果出现 `"coordinates": null` 或 `"geometries": null`，属于畸形结构，按规范必须计入无效几何（`invalid_geom_count = 1`）。
- **要素空几何（Feature null geometry）**：
  Feature 对象的 `"geometry": null` 属于合法的未定位要素（Unlocated Feature），严格保留其语义为 `null_geom_count = 1`，不可计为 `invalid_geom_count`。
- **存在但缺少/空类型的 Geometry 对象**：
  若要素的 `geometry` 为字典对象但其 `type` 字段缺失或为空字符串（如 `{"type": ""}` 或 `{}`），不属于未定位要素，而是格式畸形的几何对象，统一判定计入 `invalid_geom_count = 1`。
- **非空坐标数组内的嵌套空元素**：
  在非空坐标数组中，位置本身必须至少含 2 个分量（如 `LineString` 的 `[[100, 30], []]` 或 `[[]]` 中的空分量），Polygon 的环线必须由有效位置组成，嵌套空分量/空环线均判定为无效。
- **GeometryCollection 递归**：
  递归校验所有子几何，确保某一子几何的错误坐标不会被兄弟子几何的有效坐标所掩盖。
- **稳定边界**：
  保持当前 CRS 推断逻辑与边界框（BBox）计算稳定。

---

## 3. 修复实现方案

在 `backend/services/layer_service.py` 中实现了极简且鲁棒的几何类型与坐标校验链：

1. `_is_valid_ordinate(val)`：
   严格检查单个坐标分量为有限数值（`int`、`float`、`Real`），显式拒绝 `bool`（排除 Python `isinstance(True, int)` 隐式转换陷阱）、字符串及 `NaN`/`Inf`。
2. `_is_valid_position(pos)`：
   要求位置为长度大于等于 2 的列表或元组，且每个分量均满足 `_is_valid_ordinate`。
3. `_validate_coords(gtype, coords)`：
   - 若 `coords` 不是列表/元组，返回 `False`（拒绝 `coordinates: null`、字符串等）。
   - 若 `coords` 为根空数组 `[]`，返回 `True`（合法空几何）。
   - 依据 `gtype` 的严格嵌套层级（Point 为 0 层、MultiPoint/LineString 为 1 层、Polygon/MultiLineString 为 2 层、MultiPolygon 为 3 层）遍历校验每个位置，拒绝内部嵌套空元素与非法类型。
4. `_validate_geometry(geom)`：
   针对 `GeometryCollection` 校验其 `geometries` 成员必须为列表/元组，可以为空列表（合法空集合），非空列表则对其所有子几何递归调用 `_validate_geometry` 校验；针对其他类型委托 `_validate_coords`。
5. `inspect_geojson` 几何分类与串联校验：
   - `if geom is None`: 判定为未定位要素，`null_geom += 1; continue`。
   - `if not isinstance(geom, dict)` 或 `if not gtype or not isinstance(gtype, str)`: 判定为畸形几何，`invalid_geom += 1; continue`。
   - 在 Shapely 拓扑校验前先执行 `if not _validate_geometry(geom): invalid_geom += 1`，若结构与坐标合法再由 Shapely 进行拓扑合法性检验（如自相交检测）。

---

## 4. 聚焦测试与验证结果

### 4.1 测试命令与环境
```powershell
Set-Location E:\my_repo\Gis-WorkTable
$env:PYTHONPATH="E:\my_repo\Gis-WorkTable"
rtk .venv\Scripts\pytest backend/tests/test_layer_service.py
```

### 4.2 执行输出
```text
============================= test session starts =============================
platform win32 -- Python 3.13.0, pytest-9.1.1, pluggy-1.7.0 -- E:\my_repo\Gis-WorkTable\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: E:\my_repo\Gis-WorkTable\backend
configfile: pytest.ini
plugins: anyio-4.15.1, langsmith-0.14.11
collecting ... collected 12 items

backend\tests\test_layer_service.py::test_inspector_does_not_mark_an_invalid_explicit_crs_as_known PASSED [  8%]
backend\tests\test_layer_service.py::test_inspector_preserves_valid_non_default_crs_identifiers PASSED [ 16%]
backend\tests\test_layer_service.py::test_inspector_normalizes_recognized_geographic_and_web_mercator_crs PASSED [ 25%]
backend\tests\test_layer_service.py::test_inferred_geojson_crs_reports_degrees_and_unknown_crs_reports_no_units PASSED [ 33%]
backend\tests\test_layer_service.py::test_inspect_geojson_rejects_boolean_coordinates PASSED [ 41%]
backend\tests\test_layer_service.py::test_inspect_geojson_rejects_string_and_nonnumeric_coordinates PASSED [ 50%]
backend\tests\test_layer_service.py::test_inspect_geojson_rejects_malformed_nested_and_geometry_collection PASSED [ 58%]
backend\tests\test_layer_service.py::test_inspect_geojson_rejects_nested_empty_elements_in_non_empty_coordinates PASSED [ 66%]
backend\tests\test_layer_service.py::test_inspect_geojson_preserves_valid_and_empty_geometries_without_false_positives PASSED [ 75%]
backend\tests\test_layer_service.py::test_inspect_geojson_preserves_feature_null_geometry_as_null_count PASSED [ 83%]
backend\tests\test_layer_service.py::test_inspect_geojson_counts_missing_or_empty_geometry_type_as_invalid PASSED [ 91%]
backend\tests\test_layer_service.py::test_inspect_geojson_feature_collection_mixed_summary PASSED [100%]

============================= 12 passed in 0.32s ==============================
```

### 4.3 覆盖场景矩阵
| 测试用例函数 | 覆盖场景 | 预期断言 |
|---|---|---|
| `test_inspect_geojson_rejects_boolean_coordinates` | Point `[True, 30]`, `[100, False]`, LineString `[[100, 30], [True, 31]]`, Polygon 含 `True` | `invalid_geom_count == 1`, `null_geom_count == 0` |
| `test_inspect_geojson_rejects_string_and_nonnumeric_coordinates` | Point `["100", "30"]`, `[100, "30"]`, `[NaN, 30]`, `[Inf, 30]`, 少于 2 分量 `[100]` | `invalid_geom_count == 1`, `null_geom_count == 0` |
| `test_inspect_geojson_rejects_malformed_nested_and_geometry_collection` | `coordinates: None`, `geometries: None`, `geometries: "invalid"`, GC 混入错误子几何, 嵌套 GC 畸形 | `invalid_geom_count == 1`（子几何错误不被掩盖） |
| `test_inspect_geojson_rejects_nested_empty_elements_in_non_empty_coordinates` | Polygon `[[]]`, Polygon 混入空环 `[ring, []]`, LineString `[[]]`, LineString `[[100, 30], []]`, MultiPolygon `[[[]]]` | `invalid_geom_count == 1` |
| `test_inspect_geojson_preserves_valid_and_empty_geometries_without_false_positives` | 2D/3D Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon, 以及各类型根 `coordinates: []`、空 GC | `invalid_geom_count == 0`, `null_geom_count == 0`（防假阳性） |
| `test_inspect_geojson_preserves_feature_null_geometry_as_null_count` | Feature `geometry: None` | `null_geom_count == 1`, `invalid_geom_count == 0` |
| `test_inspect_geojson_counts_missing_or_empty_geometry_type_as_invalid` | Feature `geometry: {"type": ""}`, `geometry: {}`, `geometry: {"type": 123}` | `null_geom_count == 0`, `invalid_geom_count == 1` |
| `test_inspect_geojson_feature_collection_mixed_summary` | 混合 6 要素集合（有效点、布尔点、字符点、空点、null 要素、有效线） | `feature_count: 6`, `null: 1`, `invalid: 2`, BBox 与 CRS 推断均正确 |

---

## 5. 限制说明与上下文状态

1. **未引入外部依赖与网络**：完全复用 Python 标准库与已存在的 Shapely，无新依赖与网络开销。
2. **Git 干净度**：除指定的 2 个修改文件与 1 个新建文档文件外，未改动任何其它文件，未执行 `git commit`。
3. **UI 上下文状态（Antigravity context meter）**：UI 界面未显示上下文仪表盘用量/剩余量数值（Recorded as Not shown / Not displayed）。
