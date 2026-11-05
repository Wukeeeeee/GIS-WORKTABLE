# GIS WorkTable `.giswork` 工程包导出/导入往返可靠性交接报告

## 1. 实际改动文件 (Owned Files Only)

本次更新严格限制在指定的个人所有权文件范围内，未触碰任何共享未提交代码或用户正在编辑的工作区文件：

- `backend/services/project_service.py`：修复内容寻址栅格资产完整性校验与 `load_project` 中 `source_asset`-only 图层的动态重写。
- `backend/tests/test_project_raster_persistence.py`：新增 3 项回归与往返测试（被篡改内容寻址栅格拒绝、矢量工程全量导出/导入往返、仅含源栅格图层的导入与重新加载）。
- `docs/validation/project-package-roundtrip-handoff.md`：本交接文档。

用户所有文件（`backend/services/sql_engine.py`、`tools.py`、`workflow.py` 及其测试与 `docs/validation/module-scan-progress.md`）均保持原状未做任何修改。

---

## 2. 复现缺口与根因分析

### 缺口 1：受管栅格资源缺少内容寻址哈希校验，损坏/篡改数据被静默导入
- **复现方式**：通过真实 GeoTIFF 导出 `.giswork` 工程包后，将包内受管资产 `assets/<sha20>.tif` 修改为任意损坏字节，保持文件名与 `project.json` 不变。在修复前调用 `import_project`。
- **原始结果**：`import_project` 仅校验了文件存在与相对路径，静默将损坏内容加密导入本地工程目录并记录至 `index.json` 返回成功；后续调用 `get_project_raster_asset` 或栅格分析计算时，由于底层 GDAL 无法解析该文件抛出异常，在用户工程库中留下损坏半成品。
- **根因**：`_store_raster_asset` 保存时以 SHA-256 前 20 位 16 进制字符为资产命名（即 `<sha20>.<ext>` 内容寻址契约），但在 `import_project` 遍历检验 `asset`/`source_asset` 时，缺乏针对该契约的校验逻辑（不同于矢量 blob 校验了 12 位 SHA-256 哈希）。

### 缺口 2：`load_project` 对仅有 `source_asset` 的栅格图层未重写旧机器 `project_id` 与 `source_url`
- **复现方式**：导入一个在 `project.json` 中显式携带旧机器 `project_id: "old-machine-pid"` 与陈旧 `source_url: "/api/projects/old-machine-pid/assets/<asset_name>"`、但仅包含 `source_asset`（无预览切片 `asset`）的合法栅格工程包。导入并在新会话中加载/激活。
- **原始结果**：由于原有逻辑仅在 `raster.get("asset")` 存在时才触发重写，因此仅含 `source_asset` 的图层在 `load_project` 返回时依然残留导出包内的陈旧 `source_url`（指向不存在的 `old-machine-pid`），导致后续向该 URL 发起 HTTP GET 请求返回 404，`tools._find_uploaded_tif` 无法定位原始 TIFF。
- **修复验证**：修复后即使工程包元数据带有陈旧 `source_url` 与 `project_id`，`load_project` 依然会将其动态重写为新工程的 `/api/projects/<new-id>/assets/<asset_name>`，GET 请求成功返回 200 及原始 TIFF 字节，下游客观查找与计算恢复正常。

---

## 3. 实现决定

1. **兼容性内容寻址校验**：
   在 `import_project` 的栅格资源循环中，利用正则匹配现代受管资产命名规则 `r"([0-9a-f]{20})\.[^.]+"`。命中该规则时，以 1MB 分块流式计算 SHA-256，要求其前 20 位与文件名严格一致；若不一致，立即清理导入临时目录 `target_dir` 并抛出 `ValueError("导入的工程文件包含不匹配的栅格资源数据")`。对于不符合该命名规则的合法旧工程资产（如 `preview.png`），自动跳过哈希校验，仅保留存在性与路径安全校验，确保向后兼容。
2. **单点动态派生运行时 URL**：
   在 `load_project` 的图层解析中，将判断扩展为 `if isinstance(raster, dict) and (raster.get("asset") or raster.get("source_asset")):`，统一在此处为返回给调用方的图层动态注入当前的 `project_id`、`url` 与 `source_url`，避免将本地临时运行时的绝对/相对路径强行固化写入 `.giswork` 包持久化元数据中。
3. **失败原子清理**：
   在发生哈希不匹配、文件缺失或解压异常时，确保 `target_dir` 被完整清除，不写入 `index.json`，不残留无效工程与孤儿文件。

---

## 4. 运行的命令与逐项结果

全部检查均在代码库根目录 `E:\my_repo\Gis-WorkTable` 下使用项目 Python 环境运行：

1. **基线检查命令**：
   ```powershell
   Set-Location -LiteralPath 'E:\my_repo\Gis-WorkTable'; & 'D:\python\python.exe' -m pytest -q backend/tests/test_project_service_import.py backend/tests/test_project_raster_persistence.py -p no:cacheprovider --tb=short
   ```
   **结果**：49 passed in 11.32s。

2. **最终针对性验证命令**：
   ```powershell
   Set-Location -LiteralPath 'E:\my_repo\Gis-WorkTable'; & 'D:\python\python.exe' -m pytest -q backend/tests/test_project_service_import.py backend/tests/test_project_raster_persistence.py -p no:cacheprovider --tb=short
   ```
   **结果（Gemini 最终运行）**：52 passed in 12.91s。
   **结果（GPT 独立复验）**：52 passed in 10.68s。
   - `backend/tests/test_project_service_import.py`: 2 项全部通过（子进程隔离下的安全性与导入行为无凭据调用校验）。
   - `backend/tests/test_project_raster_persistence.py`: 50 项全部通过。其中包含新增的 3 项回归：
     - `test_import_rejects_hashed_raster_asset_with_tampered_bytes`: 验证被篡改的 TIFF 资源在导入时被精确拦截，工程列表为空，项目目录无残留。
     - `test_vector_project_export_import_roundtrip`: 验证矢量多边形与点图层的几何坐标、属性、对话历史、地图状态 `mapState`、样式与注册令牌完整往返。
     - `test_source_asset_only_layer_survives_import_and_reload`: 验证仅含 `source_asset` 的栅格工程导入激活后，新 `source_url` 指向新工程并可读取原始 TIFF 字节，下游客观查找函数正常工作。

---

## 5. 兼容性判断

- **API 兼容性**：`export_project(pid: str) -> bytes` 与 `import_project(zip_bytes) -> dict` 函数签名与返回值契约完全保持一致。
- **文件包格式兼容性**：`.giswork` ZIP 格式未添加任何自定义私有结构，保留 `project.json`、`blobs/` 与 `assets/`。
- **旧工程向后兼容**：非 20 位哈希命名的旧工程包资源不会触发哈希比对，合法旧包导入不受影响。
- **无新依赖引入**：仅使用标准库 `hashlib`、`re` 与项目既有内部模块，未增加外部第三方库依赖。

---

## 6. 假设与未验证事项

- **假设**：所有遵循 `<20位小写16进制>.<扩展名>` 命名的栅格资产，均被视作已建立内容寻址完整性契约的受管资产。
- **未验证事项**：
  1. 完整 Electron 客户端界面端到端拖放测试未在本轮运行（仅在 FastAPI TestClient 与后端服务层验证）。
  2. 真实外网远程云原生 COG 影像下载（受网络环境限制，在当前本地回归中排除）。

---

## 7. 上下文用量报告 (Context Meter)

- **显示状态**：not displayed（当前 Antigravity 交互会话环境中未提供实时数值/单位的 Context Meter 读数）。
