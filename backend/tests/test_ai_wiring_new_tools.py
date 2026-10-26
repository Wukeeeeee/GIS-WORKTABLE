# -*- coding: utf-8 -*-
"""AI 助手提示词与 20 个新工具的接线测试（静态，不调用 LLM）。

覆盖：
- 20 个新工具名全部出现在通用 SYSTEM_PROMPT（以及 GLM 精简提示词）中
- 关键路由指引存在：join_field vs spatial_join、raster_reclassify vs raster_calculator、
  cost_distance/least_cost_path 是栅格代价面而非路网、surface_volumes 同网格 DEM、
  spatial_regression 数值字段、geometry_attributes 自动投影、spatial_weights_matrix 前置复用
- 20 个新工具已注册进 live registry
- 提示词中引用的工具名都存在于 registry（防拼写错误 / 防陈旧工具名）
"""
import re

from backend.services.ai_service import SYSTEM_PROMPT, SYSTEM_PROMPT_GLM
from backend.services.tools import tools


NEW_TOOLS = [
    # Raster
    "raster_reclassify",
    "raster_focal_stats",
    "euclidean_distance",
    "raster_extract_by_mask",
    "surface_volumes",
    # Vector
    "join_field",
    "geometry_attributes",
    "minimum_bounding_geometry",
    "points_to_line",
    "generate_points_along_lines",
    # Stats
    "spatial_weights_matrix",
    "spatial_regression",
    "directional_distribution",
    "central_tendency",
    "od_cost_matrix",
    # Convert
    "feature_to_raster",
    "raster_to_feature",
    "create_fishnet",
    "cost_distance",
    "least_cost_path",
]

# 提示词里出现的 snake_case 标识符，但它们不是工具名（代码片段/参数/DOM id/示例变量）。
# 审计"提示词只引用已注册工具"时排除这些，避免把非工具标识符误判为陈旧工具名。
NON_TOOL_IDENTIFIERS = {
    "adjust_text",      # matplotlib 库函数
    "bbox_inches",      # savefig 参数
    "ax_map", "ax_table", "ax_list",  # 示例子图变量
    "choice_key", "region_disambiguation",  # ask_user_choice 参数/取值
    "layer_name", "place_name", "sub_district", "min_samples",  # 工具参数
    "feature_filter", "feature_type", "target_filter", "target_layer", "task_id",  # 新增工具参数/任务上下文
    "points_data",      # 示例变量
    "current_amap_key", # 凭据变量，不是可调用 GIS 工具
}

TOOL_TOKEN_RE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+")


def _tool_tokens(prompt):
    """提取提示词中形如工具名的 snake_case 标识符。"""
    return set(TOOL_TOKEN_RE.findall(prompt))


def _lines_with(prompt, name):
    """返回包含指定工具名的提示词行（不区分出现次数）。"""
    return [ln for ln in prompt.splitlines() if name in ln]


def _registry_names():
    return {t.name for t in tools}


# ---------------------------------------------------------------
# 1) 20 个新工具名必须写进提示词
# ---------------------------------------------------------------

def test_new_tool_names_in_main_system_prompt():
    missing = [n for n in NEW_TOOLS if n not in SYSTEM_PROMPT]
    assert not missing, f"通用 SYSTEM_PROMPT 缺少新工具名: {missing}"


def test_new_tool_names_in_glm_system_prompt():
    missing = [n for n in NEW_TOOLS if n not in SYSTEM_PROMPT_GLM]
    assert not missing, f"GLM SYSTEM_PROMPT_GLM 缺少新工具名: {missing}"


def test_new_tool_count_is_twenty():
    assert len(NEW_TOOLS) == 20
    assert len(set(NEW_TOOLS)) == 20


# ---------------------------------------------------------------
# 2) 关键路由指引（最易选错的点）
# ---------------------------------------------------------------

def test_join_field_vs_spatial_join_guidance():
    """按属性字段连接用 join_field；按空间关系连接才用 spatial_join。"""
    lines = _lines_with(SYSTEM_PROMPT, "join_field")
    assert lines, "提示词未提到 join_field"
    assert any("属性" in ln for ln in lines), "join_field 指引未提及属性"
    assert any("spatial_join" in ln for ln in lines),         "join_field 指引未与 spatial_join 做对比（最易选错点）"


def test_raster_reclassify_vs_raster_calculator_guidance():
    """重分类优先 raster_reclassify；多波段任意表达式才用 raster_calculator。"""
    lines = _lines_with(SYSTEM_PROMPT, "raster_reclassify")
    assert lines, "提示词未提到 raster_reclassify"
    assert any("raster_calculator" in ln for ln in lines),         "raster_reclassify 指引未与 raster_calculator 做对比"


def test_cost_distance_is_raster_surface_not_road_network():
    """cost_distance / least_cost_path 是栅格代价面；路网用 network_analysis / od_cost_matrix。"""
    lines = _lines_with(SYSTEM_PROMPT, "cost_distance")
    assert lines, "提示词未提到 cost_distance"
    assert any(("栅格" in ln or "代价" in ln) for ln in lines),         "cost_distance 指引未说明其是栅格代价面"
    assert any(("路网" in ln) and ("network_analysis" in ln or "od_cost_matrix" in ln)
               for ln in lines),         "cost_distance 指引未把路网分析指向 network_analysis / od_cost_matrix"
    lines_lcp = _lines_with(SYSTEM_PROMPT, "least_cost_path")
    assert lines_lcp, "提示词未提到 least_cost_path"


def test_surface_volumes_requires_coregistered_dem():
    lines = _lines_with(SYSTEM_PROMPT, "surface_volumes")
    assert lines, "提示词未提到 surface_volumes"
    assert any(("同网格" in ln or "网格" in ln) and "DEM" in ln for ln in lines),         "surface_volumes 指引未说明需要同网格 DEM"


def test_spatial_regression_numeric_fields_guidance():
    lines = _lines_with(SYSTEM_PROMPT, "spatial_regression")
    assert lines, "提示词未提到 spatial_regression"
    assert any("数值" in ln for ln in lines),         "spatial_regression 指引未要求数值字段"


def test_geometry_attributes_projection_guidance():
    lines = _lines_with(SYSTEM_PROMPT, "geometry_attributes")
    assert lines, "提示词未提到 geometry_attributes"
    assert any("投影" in ln for ln in lines),         "geometry_attributes 指引未说明经纬度下自动投影"


def test_spatial_weights_matrix_guidance_does_not_claim_prerequisite():
    lines = _lines_with(SYSTEM_PROMPT, "spatial_weights_matrix")
    assert lines, "提示词未提到 spatial_weights_matrix"
    assert any("不是" in ln and "前置" in ln and "各自构建" in ln for ln in lines), \
        "spatial_weights_matrix 指引必须说明它不是 Moran/OLS 的前置输入"


# ---------------------------------------------------------------
# 3) 20 个新工具必须已注册进 live registry
# ---------------------------------------------------------------

def test_all_new_tools_registered_in_live_registry():
    registered = _registry_names()
    missing = sorted(n for n in NEW_TOOLS if n not in registered)
    assert not missing, (
        "以下新工具尚未注册进 backend.services.tools.tools: " + ", ".join(missing)
    )


# ---------------------------------------------------------------
# 4) 提示词引用的工具名必须都存在于 registry（防拼写错误）
# ---------------------------------------------------------------

def test_prompt_references_only_registered_tools():
    registered = _registry_names()
    referenced = _tool_tokens(SYSTEM_PROMPT) - NON_TOOL_IDENTIFIERS
    stale = sorted(n for n in referenced if n not in registered)
    assert not stale, (
        "SYSTEM_PROMPT 引用了注册表中不存在的工具名（疑似拼写错误或陈旧工具名）: "
        + ", ".join(stale)
    )


def test_glm_prompt_references_only_registered_tools():
    registered = _registry_names()
    referenced = _tool_tokens(SYSTEM_PROMPT_GLM) - NON_TOOL_IDENTIFIERS
    stale = sorted(n for n in referenced if n not in registered)
    assert not stale, (
        "SYSTEM_PROMPT_GLM 引用了注册表中不存在的工具名（疑似拼写错误或陈旧工具名）: "
        + ", ".join(stale)
    )
