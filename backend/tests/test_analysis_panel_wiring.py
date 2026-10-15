# -*- coding: utf-8 -*-
"""静态接线测试：分析工具面板（frontend/js/analysis_tools.js）。

不启动浏览器、不调用后端，只做源码级检查：
- 20 个冻结工具名全部出现在面板文件中，且 OPS 恰好 20 条、按 4 组 optgroup 分组；
- 每个工具的主参数名与后端接口契约一致；
- 面板通过 GIS.workspace.preparePanel 接入统一标题栏（3 个必需 id）；
- 使用 GIS.api.invokeTool / GIS.api.syncLayer 直连后端；
- 结果与错误经 GIS.workspace.toolFeedback 渲染在面板内，运行期间禁用按钮；
- 定位仅使用 GIS.workspace.centerPanel / clampPanel，不写死坐标；
- 面板文件不含 emoji / 装饰性字符、不新增 <style> 或 CSS 文件引用；
- 引用的 --ui-icon-image 图标文件必须真实存在；
- 只用既有的公共 class，GIS.analysisTools 导出存在；
- frontend/index.html 已包含 <script src="js/analysis_tools.js"></script> 与菜单入口。
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS_PATH = os.path.join(ROOT, "frontend", "js", "analysis_tools.js")
INDEX_PATH = os.path.join(ROOT, "frontend", "index.html")
ICON_DIR = os.path.join(ROOT, "frontend", "assets", "ui-icons")

FROZEN_TOOLS = [
    # 栅格
    "raster_reclassify",
    "raster_focal_stats",
    "euclidean_distance",
    "raster_extract_by_mask",
    "surface_volumes",
    # 矢量与属性
    "join_field",
    "geometry_attributes",
    "minimum_bounding_geometry",
    "points_to_line",
    "generate_points_along_lines",
    # 空间统计
    "spatial_weights_matrix",
    "spatial_regression",
    "directional_distribution",
    "central_tendency",
    "od_cost_matrix",
    # 转换与代价距离
    "feature_to_raster",
    "raster_to_feature",
    "create_fishnet",
    "cost_distance",
    "least_cost_path",
]

# 每个工具必须出现的主参数键（后端接口契约）
REQUIRED_ARGS = {
    "raster_reclassify": ["layer_name", "method"],
    "raster_focal_stats": ["layer_name", "stat", "size"],
    "euclidean_distance": ["layer_name"],
    "raster_extract_by_mask": ["raster_layer", "zone_layer", "inside"],
    "surface_volumes": ["before_layer", "after_layer"],
    "join_field": ["target_layer", "join_layer", "target_field", "join_field", "how"],
    "geometry_attributes": ["layer_name", "metrics"],
    "minimum_bounding_geometry": ["layer_name", "kind"],
    "points_to_line": ["layer_name", "group_field", "close_ring"],
    "generate_points_along_lines": ["layer_name", "interval", "unit"],
    "spatial_weights_matrix": ["layer_name", "method", "k"],
    "spatial_regression": ["layer_name", "dependent", "independents"],
    "directional_distribution": ["layer_name", "group_field"],
    "central_tendency": ["layer_name", "weight_field"],
    "od_cost_matrix": ["origins_layer", "destinations_layer"],
    "feature_to_raster": ["layer_name", "value_field", "cell_size"],
    "raster_to_feature": ["layer_name", "connectivity", "simplify"],
    "create_fishnet": ["extent_layer", "cell_size"],
    "cost_distance": ["cost_layer", "source_layer"],
    "least_cost_path": ["cost_layer", "source_layer", "destination_layer"],
}

# 图层参数由 _run 动态写入（args[layer_arg] = ...），其余参数必须是字面量 args.xxx
LAYER_ARG_KEYS = {
    "layer_name", "raster_layer", "zone_layer", "before_layer", "after_layer",
    "target_layer", "join_layer", "origins_layer", "destinations_layer",
    "extent_layer", "cost_layer", "source_layer", "destination_layer",
}
# 允许的 class（均为 workspace.css 既有样式）
ALLOWED_CLASSES = {
    "spatial-panel",
    "spatial-toolbar",
    "spatial-toolbar-title",
    "spatial-toolbar-close",
    "spatial-body",
    "spatial-field",
    "spatial-input",
    "spatial-run-btn",
    "ui-icon",
}

# 明确禁止的装饰性排版符号（非 emoji 区块）
DECORATIVE = set("\u2713\u2714\u2715\u2716\u2717\u2605\u2606\u26a0\u2795\u270e\u2709\u2611\u25b6\u23f3\u2190\u2192\u2191\u2193")


@pytest.fixture(scope="module")
def js_text():
    with open(JS_PATH, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def index_text():
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return f.read()


def test_panel_file_exists():
    assert os.path.isfile(JS_PATH), JS_PATH


def test_all_frozen_tool_names_present(js_text):
    assert len(FROZEN_TOOLS) == 20
    missing = [t for t in FROZEN_TOOLS if t not in js_text]
    assert not missing, "面板缺少工具: %s" % missing


def test_ops_count_and_no_extra_tools(js_text):
    ops_tools = re.findall(r"tool: '([a-z_0-9]+)'", js_text)
    assert len(ops_tools) == 20, "OPS 应恰好 20 条，实际 %d" % len(ops_tools)
    assert len(set(ops_tools)) == 20, "OPS 工具名重复: %s" % ops_tools
    assert set(ops_tools) == set(FROZEN_TOOLS), \
        "OPS 工具集合与冻结清单不一致: 多=%s 少=%s" % (
            sorted(set(ops_tools) - set(FROZEN_TOOLS)),
            sorted(set(FROZEN_TOOLS) - set(ops_tools)))


def _ops_entries(js_text):
    """把 OPS 数组解析为 [{tool, extra, layers}]（每条 OPS 一行）。"""
    out = []
    for line in js_text.splitlines():
        m = re.search(r"tool:\s*'([a-z_0-9]+)'", line)
        if not m:
            continue
        extra = re.search(r"extra:\s*'([^']+)'", line)
        layers = re.findall(r"'(layer_name|[a-z]+_layer)'", line)
        out.append({"tool": m.group(1),
                    "extra": extra.group(1) if extra else "",
                    "layers": layers})
    return out


def _run_branch_source(js_text, extra):
    """截取 _run() 中处理该 extra 的分支源码（可能是首个 if，或后续 else if）。"""
    markers = ["if (e === '%s') {" % extra, "} else if (e === '%s') {" % extra]
    start = -1
    for mk in markers:
        # 只取 _run 内部出现的那一处
        run_pos = js_text.find("var e = op.extra || '';")
        pos = js_text.find(mk, run_pos if run_pos >= 0 else 0)
        if pos >= 0 and (start < 0 or pos < start):
            start = pos
    if start < 0:
        return None
    nxt = js_text.find("} else if (e === '", start + 1)
    nxt2 = js_text.find("return _invoke(op.tool, args);", start + 1)
    if nxt < 0 or (0 <= nxt2 < nxt):
        nxt = nxt2
    return js_text[start:nxt if nxt >= 0 else len(js_text)]


def test_ops_entries_parsed(js_text):
    ops = _ops_entries(js_text)
    assert len(ops) == 20, "OPS 应解析出 20 条，实际 %d" % len(ops)
    assert {o["tool"] for o in ops} == set(FROZEN_TOOLS)


def test_required_primary_args_per_tool(js_text):
    """每个工具的主参数必须写在它自己的参数装配分支里。"""
    ops = {o["tool"]: o for o in _ops_entries(js_text)}
    assert set(REQUIRED_ARGS) == set(FROZEN_TOOLS)
    for tool, keys in REQUIRED_ARGS.items():
        op = ops[tool]
        branch = _run_branch_source(js_text, op["extra"]) if op["extra"] else None
        for key in keys:
            if key in LAYER_ARG_KEYS:
                ok = ("'%s'" % key) in js_text or ('"%s"' % key) in js_text
            else:
                # 非图层参数必须真实写进该工具自己的参数装配分支
                ok = (branch is not None and
                      re.search(r"args\.%s\b" % re.escape(key), branch) is not None)
            assert ok, "%s 缺少参数 %s" % (tool, key)


def test_exports_analysis_tools(js_text):
    # 必须是未注释的真实导出语句
    m = re.search(r"^\s*GIS\.analysisTools\s*=\s*\{", js_text, re.M)
    assert m, "缺少 GIS.analysisTools 导出"
    for api in ("init", "activate", "deactivate", "toggle", "openWith"):
        assert api in js_text, "缺少接口 %s" % api


def test_prepare_panel_with_required_ids(js_text):
    m = re.search(
        r"preparePanel\(\s*'analysisToolsPanel'\s*,\s*'analysisToolsToolbar'\s*,\s*'analysisToolsClose'",
        js_text,
    )
    assert m, "必须调用 preparePanel('analysisToolsPanel','analysisToolsToolbar','analysisToolsClose',...)"
    assert "GIS.workspace.preparePanel" in js_text


def test_required_ids_and_container_ids(js_text):
    for eid in ("analysisToolsPanel", "analysisToolsToolbar", "analysisToolsClose",
                "analysisToolsPanelWrapper", "analysisToolsPanelContainer"):
        assert eid in js_text, "缺少 id %s" % eid


def test_direct_invoke_and_sync(js_text):
    assert "GIS.api.invokeTool" in js_text, "必须使用 GIS.api.invokeTool 直连工具"
    assert "GIS.api.syncLayer" in js_text, "执行前必须同步图层 GIS.api.syncLayer"


def test_feedback_and_busy_state(js_text):
    assert "toolFeedback(panelId" in js_text, \
        "结果/错误必须经 GIS.workspace.toolFeedback(panelId, ...) 渲染在面板内"
    assert "toolPending(panelId" in js_text, \
        "执行期间应经 GIS.workspace.toolPending 标记忙碌（禁用运行按钮）"
    assert re.search(r"\.disabled\s*=\s*true", js_text), "运行期间必须禁用运行按钮"


def test_positioning_uses_workspace_helpers(js_text):
    assert "centerPanel" in js_text, "定位必须使用 GIS.workspace.centerPanel"
    assert "clampPanel" in js_text, "定位必须使用 GIS.workspace.clampPanel"
    # 不得出现硬编码的 left/top 像素定位字面量
    assert not re.search(r"style\.left\s*=\s*'?\d+", js_text)
    assert not re.search(r"style\.top\s*=\s*'?\d+", js_text)


def test_only_existing_classes(js_text):
    used = set()
    for m in re.finditer(r'class=\\?"([^"\\]+)\\?"', js_text):
        for cls in m.group(1).split():
            used.add(cls)
    unknown = used - ALLOWED_CLASSES
    assert not unknown, "使用了非既有 class: %s" % sorted(unknown)
    for cls in ("spatial-panel", "spatial-toolbar", "spatial-toolbar-title",
                "spatial-toolbar-close", "spatial-body", "spatial-field",
                "spatial-input", "spatial-run-btn"):
        assert cls in used, "缺少公共 class %s" % cls


def test_layer_dropdown_from_api(js_text):
    assert "/api/layers/names" in js_text, "图层下拉必须从 /api/layers/names 读取"


def test_optgroups_present(js_text):
    assert js_text.count("optgroup") >= 1, "应使用 optgroup 分组"
    for label in ("栅格分析", "矢量与属性", "空间统计", "转换与代价距离"):
        assert label in js_text, "缺少分组标签 %s" % label


def test_no_emoji_or_decorative_glyphs(js_text):
    bad = []
    for ch in js_text:
        cp = ord(ch)
        if 0x1F000 <= cp <= 0x1FAFF:      # emoji 主体
            bad.append(ch)
        elif 0x2600 <= cp <= 0x27BF:      # 杂项符号 / dingbats
            bad.append(ch)
        elif 0x2B00 <= cp <= 0x2BFF:
            bad.append(ch)
        elif 0x2190 <= cp <= 0x21FF:
            bad.append(ch)
        elif cp in (0xFE0F, 0x20E3):
            bad.append(ch)
        elif ch in DECORATIVE:
            bad.append(ch)
    assert not bad, "面板含 emoji/装饰性字符: %s" % sorted(set(bad))


def test_no_new_css(js_text):
    assert "<style" not in js_text.lower(), "不得新增 <style> 块"
    assert ".css\" " not in js_text and not re.search(r"[\x27\"]([^\x27\"]*\.css)[\x27\"]", js_text), "不得引用新 CSS 文件"
    assert "css/" not in js_text, "不得引用新 CSS 文件"


def test_referenced_icons_exist(js_text):
    refs = re.findall(r"--ui-icon-image:url\('(/assets/ui-icons/[^']+)'\)", js_text)
    assert refs, "面板应使用 .ui-icon PNG 图标（或完全不使用）"
    for ref in refs:
        filename = os.path.basename(ref)
        assert os.path.isfile(os.path.join(ICON_DIR, filename)), \
            "引用了不存在的图标: %s" % filename


def test_index_html_includes_analysis_tools(index_text):
    assert "js/analysis_tools.js" in index_text, "index.html 未包含 analysis_tools.js"
    assert 'data-action="tool-analysis-tools"' in index_text, "index.html 缺少分析工具菜单入口"