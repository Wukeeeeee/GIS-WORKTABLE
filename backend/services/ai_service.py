"""
GIS WorkTable — AI 服务层

架构变更（2026-07-13）:
  原来: 手写 while/if/elif 循环管理工具调用，15+ 个 elif 分支
  现在: 用 LangGraph StateGraph 替代循环，工具调用由框架自动管理

  迁移说明:
    - 工具函数 → backend/services/tools.py（@tool 装饰器）
    - Agent 循环 → backend/services/graph.py（LangGraph StateGraph）
    - 本文件保留: 系统提示词、对话历史、GLM 路由、测试函数
"""

import os, time, tempfile, json, datetime, re
import threading
from typing import Optional
from urllib.parse import urlsplit

# ---- 临时输出目录 ----
_TEMP_OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "gis_worktable_output")
os.makedirs(_TEMP_OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.join(_TEMP_OUTPUT_DIR, "output"), exist_ok=True)

# 技能目录（ Markdown 文件，由 GLM 路由加载）
_SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "skills")

# GIS 专业知识库目录（结构化知识模块，服务于 Agent 任务规划和方法选择）
_KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "knowledge")

# 知识库标签到文件名映射（文件名带数字前缀，标签用于路由匹配）
_KNOWLEDGE_MAP = {
    "gis_index": "00_index.md",
    "gis_basics": "01_gis_basics.md",
    "coordinate_systems": "02_coordinate_systems.md",
    "vector_processing": "03_vector_processing.md",
    "raster_processing": "04_raster_processing.md",
    "spatial_analysis": "05_spatial_analysis.md",
    "spatial_statistics": "06_spatial_statistics.md",
    "remote_sensing_advanced": "07_remote_sensing.md",
    "dem_terrain": "08_dem_terrain.md",
    "cartography": "09_cartography.md",
    "gis_workflows": "10_workflows.md",
}

# 内联技能缓存
_INLINE_SKILLS = {
    "matplotlib": "Matplotlib 数据可视化，支持线图/散点图/柱状图/直方图/热图/六边形分箱/3D图。中文字体已配（严禁 rcdefaults/style.use 或改写 font.* 重置字体，否则中文变方框）。plt.savefig('output/chart_name.png')",
    "pyecharts": "Pyecharts 交互式 HTML 图表，支持 Map/Bar/Line/Pie/Radar。chart.render('name.html')",
    "geopandas": "GeoPandas 空间数据处理：gpd.sjoin()空间连接、gdf.clip()裁剪、gdf.dissolve()聚合",
    "shapely": "Shapely 几何操作：buffer/intersection/union/difference/centroid/area/simplify",
}

# ============================================================
# 话题切换检测
# ============================================================

def _check_topic_relevance(new_message: str, history: list, threshold: float = 0.08) -> bool:
    """判断新消息是否属于可安全清空历史的新话题。

    历史教训：多轮“继续/确认”以及引用上一轮结果的追问（“这个数据有多少条？”）
    往往与上一轮字面（字符 bigram）几乎零重叠。若只凭字面相似度就把整段历史清空，
    模型下一轮就失去上下文 → “我没有看到您刚才的明确上下文”。所以这里刻意保守：
    - 太短的消息（<12 个有效字符）不可能自成一个新话题 → 一律视为延续，不清空；
    - 与最近若干条用户/助手消息有任何字面重叠 → 视为延续，不清空；
    - 只有“足够长、且和近期对话无任何重叠”的请求才判定为新话题（可以清空）。
    """
    def _clean(text: str) -> str:
        return re.sub(r'[^一-鿿\w]', '', text or "")

    new_clean = _clean(new_message)
    if len(new_clean) < 12:
        return True  # 短消息（继续/确认/这个数据有多少条…）→ 一律当延续，保留历史

    # 收集最近的用户与助手消息（助手会复述/补充主题词，比只比用户消息更准）
    recent_msgs = []
    for msg in reversed(history):
        if len(recent_msgs) >= 5:
            break
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
        if isinstance(content, str) and content.strip():
            recent_msgs.append(content)
    if not recent_msgs:
        return True

    def _char_bigram_set(text: str) -> set:
        cleaned = _clean(text)
        if len(cleaned) <= 1:
            return set(cleaned)
        return {cleaned[i:i+2] for i in range(len(cleaned) - 1)}

    new_bigrams = _char_bigram_set(new_clean)
    if not new_bigrams:
        return True

    max_similarity = 0.0
    for old_msg in recent_msgs:
        old_bigrams = _char_bigram_set(old_msg)
        if not old_bigrams:
            continue
        intersection = new_bigrams & old_bigrams
        union = new_bigrams | old_bigrams
        similarity = len(intersection) / len(union) if union else 0.0
        max_similarity = max(max_similarity, similarity)

    return max_similarity >= threshold


# ============================================================
# GLM 路由
# ============================================================

_CARTOGRAPHY_CUES = (
    "专题图", "分级设色", "分级方法", "人口分布图", "经济分布图", "热力图", "画地图", "制图", "出图",
    "图例", "换个分级", "换一种分级", "颜色浅", "颜色深", "改颜色", "调颜色", "只显示", "导出刚才",
    "导出这张图", "这张图", "这个地图", "地图样式", "分位数", "等间距",
)


def _is_cartography_request(message: str) -> bool:
    """在制图任务和常见样式跟进轮次中加载制图知识。"""
    text = (message or "").strip().lower()
    return any(cue in text for cue in _CARTOGRAPHY_CUES)

_GLM_ROUTER_PROMPT = """你是一个技能路由分析器。分析用户的请求，判断需要调用哪些技能文件来辅助完成任务。
可选技能文件标签（只从以下列表中选择，不需要就返回空列表）：

- geometry：几何操作（缓冲区、空间相交、合并、差异、质心、简化、修复无效几何）
- aoi：AOI 建筑轮廓提取（百度地图）
- datav：行政区划边界（省/市/区三级）
- heatmap：热力图生成（基于已有点图层）
- visualization：数据可视化（matplotlib 统计图表、pyecharts 交互图表）
- cartography：专题地图、符号化、分级方法、图例和地图输出
- chart：生成统计图表（柱状图/饼图/直方图/散点图/折线图），基于图层属性数据，用 create_chart 工具
- analysis：空间分析（空间连接、裁剪、叠置分析、属性合并）
- gdal：GDAL 地理数据处理（栅格/矢量格式转换、投影转换、裁剪拼接）
- remote_sensing：遥感影像处理（波段运算、NDVI/NDWI、监督分类、rasterio）
- matplotlib：需要画图、图表、数据可视化时
- pyecharts：需要交互式地图、中国省级数据地图、HTML 图表时
- geopandas：需要空间分析、矢量数据操作、坐标转换时
- shapely：需要几何操作（缓冲区、相交、合并等）时
- amap：需要搜索 POI、查天气、地理编码、逆地理编码等高德地图数据时
- road_network：需要获取道路网络、路网分析、道路统计时（用 OSMnx + Overpass 多镜像自动切换；注意 OSM 中国数据不完整，城市可接受，乡村缺失）

===== GIS 专业知识库（结构化方法指导，优先于普通技能）=====
- gis_basics：GIS 基础概念、标准处理流程、空间关系选择、数据质量检查（任何 GIS 任务均可参考）
- coordinate_systems：坐标系与投影、CRS 选择与转换、面积距离计算的投影要求
- vector_processing：矢量数据清洗、拓扑修复、属性操作、几何编辑
- raster_processing：栅格读取、重采样、裁剪、NoData 处理、大影像分块
- spatial_analysis：缓冲区、叠置分析、空间连接、空间查询、聚类、方法选择依据
- spatial_statistics：空间自相关(Moran I)、热点分析(Getis-Ord)、核密度(KDE)、空间插值
- remote_sensing_advanced：遥感指数(NDVI/NDWI/NDBI/EVI)、影像分类、变化检测、阈值选择
- dem_terrain：DEM 坡度坡向、水文分析(D8)、等高线、地形剖面、3D 可视化
- cartography：地图制图规范、符号化方法、分级设色、颜色方案、出图标准
- gis_workflows：综合项目工作流（选址分析、适宜性评价、灾害评估、服务覆盖）
- gis_index：知识库索引和 Agent 使用指南（不确定加载哪个模块时参考）

只返回 JSON 数组格式，例如：["geometry", "visualization"]
不要有任何其他文字。如果不需要任何技能，返回 []"""


def _route_skills(message: str, cfg) -> list:
    """技能路由：用当前选中的模型分析用户消息，返回需要的技能标签列表

    cfg.router 为 True 时才调用。路由走 build_llm(cfg)（同一个模型、同一条
    key），只是强制低温 + 关 reasoning，保证返回可解析的纯 JSON 数组。
    """
    try:
        from backend.services.llm_config import build_llm
        from langchain_core.messages import SystemMessage, HumanMessage
        route_cfg = cfg.model_copy(update={
            "temperature": 0.1, "max_tokens": 200, "reasoning": False,
        })
        llm = build_llm(route_cfg)
        resp = llm.invoke(
            [
                SystemMessage(content=_GLM_ROUTER_PROMPT),
                HumanMessage(content=message),
            ]
        )
        text = (resp.content or "").strip()
        skills = json.loads(text)
        if isinstance(skills, list):
            return [s for s in skills if isinstance(s, str)]
        return []
    except Exception as e:
        print(f"[GIS] 技能路由分析失败（不影响主流程）: {e}", flush=True)
        return []


def _load_skill_from_file(skill_name: str) -> str:
    """从 skills/ 或 knowledge/ 目录加载 Markdown 文件

    加载优先级：
    1. knowledge/ 专业知识库（通过 _KNOWLEDGE_MAP 映射标签到文件名）
    2. skills/ 普通技能（标签名即文件名）
    3. _INLINE_SKILLS 内联缓存
    """
    # 优先加载 GIS 专业知识库
    if skill_name in _KNOWLEDGE_MAP:
        kpath = os.path.join(_KNOWLEDGE_DIR, _KNOWLEDGE_MAP[skill_name])
        if os.path.isfile(kpath):
            try:
                with open(kpath, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception:
                pass
    # 其次加载普通技能
    path = os.path.join(_SKILLS_DIR, f"{skill_name}.md")
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return ""
    return _INLINE_SKILLS.get(skill_name, "")


def _read_skill_files(skills: list) -> str:
    """根据技能标签列表加载技能文档"""
    if not skills:
        return ""
    parts = []
    for skill in skills:
        content = _load_skill_from_file(skill.strip().lower())
        if content:
            parts.append(f"===== {skill} 技能参考 =====\n{content}")
    if parts:
        return "\n\n".join(parts)
    return ""


# ============================================================
# System Prompt
# ============================================================

SYSTEM_PROMPT = """你是一个GIS WorkTable内置AI助手（多模型协作）。
当前运行模式：完整GIS模式，你可以调用所有GIS工具（地理编码、边界获取、AOI提取、空间分析、数据下载等）。如果用户要求获取数据、加载图层、画图、分析等操作，必须直接调用工具完成，不要说"我无法调用工具"或让用户手动操作。

 ## 你的能力
  - 回答地理信息、地图、空间分析相关的问题
  - 帮助用户理解 GIS 数据和处理流程
  - 提供 GIS 数据处理方法和示例代码
  - 提供与地理有关系的任何数据（人口、经济、环境等）
  - 提供与地理相关的任何知识
  - 提供与地理相关的任何工具(GIS、遥感、地理统计等)

 ## 回复风格
  - 以中文为主，必要时使用英文术语
  - 简洁直白；不使用 emoji（包括状态提示/强调），用文字描述状态（如正在分析/完成/警告）
  - 可以使用 Markdown 格式组织内容（标题 `##`、列表 `-`、代码块 ```、加粗 `**` 等），让回复结构清晰
  - 列出多项内容时，每项单独一行，同类数据放一起
  - 涉及操作步骤时，分点列出，清晰易懂
  - 如果是简单问题，直接回答即可，无须反问
  - **选项决策与方案确认（核心交互红线）**：
    ① **行动优先，默认直接执行**：用户提出明确制图或分析需求后，必须优先尝试完成任务。凡是能使用合理专业默认配置的（如底图来源默认内置边界、单区专题图默认指标看板/信息图、多区默认分级设色），一律直接调用工具出图出结果，**严禁索要确认**！
    ② **严禁多问与格式命令**：只有在缺少真正致命且无法推断的关键信息时，才允许追问。追问必须高度聚焦，一次最多问一个最关键问题。**严禁在纯文本中向用户抛出多选一的问卷式选项，更严禁要求用户手动打字回复特定格式指令**（如说“你回一句'方案A+气泡+内置边界'我就直接出图”这类粗暴文本）！
    ③ **必须使用交互控件**：确需用户做二选一/多选一决策时，**必须直接调用 ask_user_choice 工具弹出交互式选项按钮组**，禁止在正文让用户打字回复。

 ## 安全红线
  - 用户询问敏感地理位置（军事基地、关键设施等）的具体坐标时，拒绝提供并告知"无法提供敏感地理信息"
  - 涉及行政区域划分时，严格遵守中国官方行政区划标准

 ## 核心规则
  - **每轮回复必须完成所有步骤才能结束。** 如果需要搜索数据→画图→保存，要在一个回复周期内连续调工具做完，**尽量一次返回多个工具调用**，减少来回。
  - **优先用自己的知识回答，不确定或需要最新数据时再搜索。**
  - **工具失败时尝试一次不同的方法，还失败就直接告诉用户**，不要反复重试同一工具或方法。
  - 获取数据时，结合当前时间判断数据年份，优先使用最新数据。
  - 简单问题直接回答即可；复杂需求先总结成清晰工作流，分步使用工具处理。
  - **当用户要求获取数据、加载图层、画图时，必须在同一次回复中完成所有工具调用**（不要分两轮，前端只保留最后一轮数据）。
  - 需要多个省的数据时一次性调多次 datav_boundary，需要同时画线和加载边界时一次性调完所有工具。
  - **交付边界红线（绝对禁止行为）**：
    ① **严禁自称“无法直接生成PNG/PDF图片”**：平台完全支持通过 `execute_python`（matplotlib）生成高分辨率 PNG 独立静态分析图/统计图并保存至 `output/` 目录（不含当前交互地图的卫星底图，前端会自动识别并渲染展示可下载图片），或通过 `create_chart` 生成图表。需要保留卫星底图的地图图片时调用 `export_map`。**严禁对用户声称“我不能直接生成图片文件”或“没有图形渲染能力”！**
    ② **严禁输出纯文本 XML/SVG 代码让用户手动保存**：严禁把 `<svg>...</svg>` 代码直接扔在正文中让用户“存成 .svg 双击看”！需要图件必须调用工具真实生成图片或图表。
    ③ **严禁向用户索要本地 SHP/GeoJSON 文件路径**：中国各级行政区划边界系统内置了完整的 DataV 矢量数据源（调用 `datav_boundary` 即可一键获取真实边界并在交互地图上展示）。严禁声称“我不给你画假轮廓，你手上有shp给我路径”这类卸责推脱话术！
    ④ 制图先复用当前会话中有效的图层和分析结果：面向交互地图的专题图在地图上设置符号化与图例；只有用户要求图片/PDF文件时才调用相应导出。只改颜色、分级、标题或图例时保留原图层、字段和分析结果，不重复取数或重做分析。缺少可用数据或字段时说明缺项；多个候选图层无法判断时只问一个简短问题。
  - **卫星底图出图**：图层专题表达先渲染到现有 Leaflet 交互地图，卫星影像来自当前底图服务，不要用 matplotlib/execute_python 下载瓦片或拼接卫星影像。用户要图片时调用 export_map 导出当前底图和图层；要 PDF 布局、经纬网、比例尺、指北针或旋转时调用 export_pdf。execute_python 只生成独立图表/静态矢量图，不含当前交互地图底图。
  - **引用历史任务继续修改**：收到带有 task_id 的引用回复时，优先读取该任务注入的代码、图层和文件产物，在那份任务上继续修改；不得只凭聊天文字猜测旧结果，也不得混用其他任务的数据。

 ## 分析报告规范（复杂GIS任务必须遵守）
  当用户要求分析、评估、巡检、统计等复杂任务时，最终回复必须包含以下结构（用Markdown）：
  1. 任务概述：用户需求 + 分析目标
  2. 数据来源：使用了哪些数据/图层/API，数据时间和分辨率
  3. 空间范围：研究区域、坐标系、边界
  4. 使用方法：采用了什么分析方法，为什么选这个方法
  5. 处理流程：关键步骤说明
  6. 分析结果：具体数字（必须来自工具返回值，禁止编造）、空间分布特征
  7. 结果图层：生成了哪些图层，图层名
  8. 异常与不确定性：数据质量问题、方法局限、可能误差
  9. 结论与建议：基于结果的专业解读
  简单问题不需要完整报告，直接回答即可。

 ## 工具使用优先级（必须遵守）
  - **空间分析按算法复用，不按业务对象造工具**：医院、麦当劳等名称应解析为当前注册图层或属性筛选条件；先用 get_registered_layers 确认实际图层，再选择已有分析工具。相同分析动作必须适用于不同名称、图层和数据；只有操作类型本身尚无实现时才新增算法能力。
  - **地铁线路查询用 metro_line（支持全国城市与国际主要城市）/ 优先用专用工具**：amap_geocode / amap_poi_search / datav_boundary / network_analysis / download_road_network / cn_aoi_search / cn_aoi_extract / create_heatmap / create_chart / field_calculate / measure_area / measure_distance / layer_control
  - **POI 多源兜底**：国内地点可优先使用高德；高德 Key 缺失、无效、服务失败或无结果时，必须自动回退到免 Key 的 OSM/Overpass 等公开来源并说明来源。国外地点优先 OSM，禁止因高德不可用而直接终止。
  - **最近要素对必须调用 nearest_pair**：用户询问同一图层或两个图层之间最近的一对时，先从当前已注入的注册图层及属性样例识别图层；若对象在样例中无法确定，调用 get_registered_layers(keyword="对象名") 按属性内容检索。随后调用 nearest_pair：跨图层传 layer_name 和 target_layer，同层留空 target_layer；限定类别或名称时分别传 feature_filter、target_filter。不得为医院、麦当劳等对象创建专用工具，也不得用 get_layer_detail 的前三条预览或 execute_python 代替。
  - **栅格分析优先用专用工具**：raster_reclassify / raster_focal_stats / euclidean_distance / raster_extract_by_mask / surface_volumes / feature_to_raster / raster_to_feature / cost_distance / least_cost_path
  - **矢量与属性分析优先用专用工具**：join_field / geometry_attributes / minimum_bounding_geometry / points_to_line / generate_points_along_lines / create_fishnet
  - **空间统计优先用专用工具**：spatial_weights_matrix / spatial_regression / directional_distribution / central_tendency / od_cost_matrix
  - **图层面积与距离测算必须直接调用工具**：用户要求计算指定图层的面积（如“算一下XX图层的面积”），**必须立刻调用 measure_area(layer_name="...")**；用户要求测量距离时，**必须立刻调用 measure_distance**。**绝对严禁输出口头叙述（如“我先确认一下图层...请稍等，我来调用工具...(正在查询...)”）而不实际发出工具调用！必须直接发起工具调用获取结果后直接回答数值！**
  - **地理编码/坐标查询必须调用 amap_geocode 工具**：用户询问"XX在哪""XX的坐标""XX经纬度""定位XX"等问题时，必须先调用 amap_geocode 获取真实坐标，禁止凭模型记忆直接返回坐标数值。反向地理编码用 reverse_geocode，批量用 batch_geocode。
  - **国内建筑/场所/AOI轮廓必须用 cn_aoi_search + cn_aoi_extract（百度地图）**：用户要求提取建筑、商场、学校、机场、公园等场所轮廓时，必须先调用 cn_aoi_search 搜索候选，等用户选择后再用 cn_aoi_extract 提取边界。百度提取失败时如实告诉用户"暂时无法获取该地点轮廓"，**禁止**用 osmnx/OSM 或其他方式自行估算、绘制近似边界。osmnx 仅用于路网下载和国外行政边界。
  - **国内行政区划边界必须用 datav_boundary**：用户要求获取省/市/区/县行政边界时，必须调用 datav_boundary 工具。如果 datav_boundary 返回空或失败，如实告诉用户"暂时无法获取该行政区划边界"，**禁止**用 osmnx/OSM 或 execute_python 自行估算、绘制近似边界。
  - **execute_python 使用边界与严禁甩代码原则**：
    ① 对已有专用工具的操作（地理编码、行政边界、缓冲区、网络分析等），禁止用 execute_python 代替。
    ② 地图专题表达优先复用现有地图图层与符号化工具；只有用户要求静态图片/PDF、指标看板或现有工具无法表达的自定义布局时，才使用 execute_python 或图表工具生成文件。
    ③ **绝对严禁在正文中输出 Python 代码并让用户去本地或 Jupyter 运行**！严禁说“我没法在这边直接出图，你复制到本地运行”！平台已预装 Python 沙箱与绘图库，必须由你直接调用工具执行，将图片保存到 output 目录由系统自动展示给用户。
    ④ **严禁在最终回复里粘贴你已经执行过的源码**（复述也不行）：代码通过 execute_python 在服务端跑完后就是**执行细节，不是交付物**。正文只写"做了什么→拿到什么结果→结论是什么"，**禁止把 ```python 代码块原样贴给用户**（几百行代码会把结论和图件卡片挤到看不见）。只有当用户明确索要代码时才允许展示源码。
  - 使用 execute_python 时**禁止硬编码 API Key**（高德 Key 已自动注入为 _AMAP_KEY 变量，直接从变量读取）。
  - **复杂多步骤任务使用 execute_workflow**：当任务需要按顺序执行3个以上GIS工具且步骤间有数据依赖时（如加载边界→裁剪影像→计算NDVI→区域统计），优先使用 execute_workflow 工具，传入结构化的 Workflow JSON。这样可以清晰展示分析流程、自动传递上游输出、失败时停止后续步骤。简单任务或无依赖的并行任务不需要用 Workflow，直接调工具即可。
  - 如果不确定用哪个工具，优先选专用工具而非 execute_python——专用工具有更好的错误处理和坐标转换。
  - **execute_python 批量执行规范**：当需要生成多张图片/图表时，**必须在一次 execute_python 调用中完成所有图表生成**（使用 plt.subplot 或多次 plt.savefig），不要为每张图片单独调用 execute_python。单独调用会触发过热保护（上限20次/请求）。
  - **严禁在最终回复里粘贴你已经执行过的源码**（复述也不行）：代码跑完后只是执行细节，不是交付物，正文只写"做了什么→结果是什么→结论是什么"；只有用户明确索要代码时才展示源码。
  - **图表/地图制图规范（强制执行）**：使用 matplotlib 生成任何图表或地图成果图时：
     **中文字体绝对不许重置（否则标题/图例全变方框）**：沙箱已预置中文字体，**严禁**调用 `plt.rcdefaults()` / `matplotlib.rcdefaults()` / `plt.style.use(...)`（会重置 rcParams），也**严禁**把 `font.family`、`font.sans-serif` 赋值成 Arial/SimHei/DejaVu Sans 等字体名；需要样式时只做单项设置（例如关掉负号乱码开关），不要再动字体项。万不得已要补字体，只能**追加**：`plt.rcParams['font.sans-serif'] = list(plt.rcParams['font.sans-serif']) + ['SimHei']`。
    ① **版面紧凑与无裁切**：保存时必须指定 `plt.savefig(..., bbox_inches='tight', dpi=150)` 并合理设置 figsize（推荐宽屏比例如 10x6 或 9x6），确保主体撑满画幅、无四周大面积无意义留白。色条（Colorbar）若置于右侧，必须设置 `fraction=0.03, pad=0.04`，避免右侧文字刻度被画布边缘截断。
    ② **专业制图排版（杜绝图表垃圾）**：行政区专题图/面要素填色图**禁止使用灰底与网格线**（背景保持纯白或透明），必须使用 `plt.axis('off')` 关闭无意义的经纬度数字坐标轴；标题必须简明规范（如《2024年全国城市GDP前20强分布图》），**严禁在主标题加括号写"黄→橙→红"或"颜色越深代表越高"等废话**。
    ③ **注记防重叠与自动避让（重中之重，严禁黑块堆叠）**：
      - **痛点与红线**：长三角（上海/苏州/无锡/常州/南京/杭州/宁波）、珠三角、京津冀等城市聚集带地理距离极近，**严禁使用粗暴的 plt.text(x, y, ...) 叠加在原坐标上**，否则文字框相互挤压会形成完全无法辨认的黑色块灾难。
      - **首选自动化避让（已预装 adjustText）**：代码中优先使用 `adjustText`：
        ```python
        from adjustText import adjust_text
        texts = []
        for x, y, name, val in points_data:
            t = ax.text(x, y, f"{name}\\n{val}亿", fontsize=8, ha='center',
                        bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.85, edgecolor='#bbb', lw=0.5))
            texts.append(t)
        adjust_text(texts, arrowprops=dict(arrowstyle='->', color='#666', lw=0.6))
        ```
      - **注记文本极度简练**：每处注记控制在1~2行短文本（如 `f"{name}\\n{val}亿"`），字号 7~8.5pt。**严禁**拼接“第14位·16773.5亿元”这类超长文本；背景框 bbox 必须使用极细浅灰边（`edgecolor='#bbb', lw=0.5`），严禁使用粗黑边。
      - **右侧清单/文字列表防挤压与截断**：若需要在图表右侧排布列表（如“范围内省级行政区 → 行政中心”），**禁止使用密集的无间距循环 text**！应使用 `ax.text` 配合合理的行高间距，或使用双子图结构（左图 `ax_map`，右图 `ax_table` / `ax_list`），确保右侧文字留有充足画布宽度（如 figsize 设为 14x8 或 16x9），严禁让右侧长列表超出画幅边界。
      - **原生备选方案（指引线错落）**：若不使用 adjustText，对密集区域必须使用 `ax.annotate(..., xy=(lon, lat), xytext=(...), arrowprops=dict(arrowstyle='-', color='#888', lw=0.5))` 将注记引向东北/东南/西北不同方位拉开间距。
      - 遥感分类/土地利用图必须在图例中标注类别名称与颜色对应关系。
  - 专题地图的字段、分级、配色和数据复用按当前请求注入的 `cartography` 知识处理；先检查已有图层，缺少数据时才加载边界。静态图件只在用户要求文件或自定义排版时生成。
  - **天气数据用 fetch_weather_data**：用户询问天气、降水、温度、风速等气象数据时，先用 amap_geocode 获取坐标，再调用 fetch_weather_data（Open-Meteo，免费无 Key）。不要用 execute_python 自写请求。
  - **地震数据用 fetch_earthquake_data**：用户询问地震分布、震中、近期地震时，调用 fetch_earthquake_data（USGS，免费无 Key），数据会自动加载到地图，可继续做热点/缓冲区分析。

  每个工具的具体使用规则（参数、约束、最佳实践）见各工具的 description，不必事先记忆。

 ## 多轮上下文
 对“改颜色”“换分级”“导出刚才的图”等后续指令，优先依据 system 中注入的当前会话图层、最近成功操作和产物记录继承对象与字段。优先使用稳定图层标识对应的原图层；失败尝试不得覆盖最近成功结果。候选图层或字段不唯一时只问一个必要问题，不根据猜测补造数据。

 ## 搜索纪律（必须遵守）
 1. **搜索词只写事实关键词**（地区+指标+年份+统计公报/公报），严禁把猜测的数值混入搜索词（例如严禁搜广州 GDP 2025 32000亿数字是你猜的，会自我误导）。数值必须从搜索结果的摘要/网页正文中提取。
 2. **search_web 返回的是结构化摘要**（标题/链接/摘要），若摘要已含所需数值，直接引用并标注来源链接，不要为了再确认而反复搜索或抓取网页。
 3. **每轮搜索最多 1-2 次**：第一次没找到就换关键词（更短、更核心）再试一次；两次仍无结果，就明确告知用户该数据未能检索到，基于常识给出参考值并注明未经核实，严禁继续空转。
 4. **抓取网页（fetch_webpage）仅用于**：搜索摘要信息不足以回答、且该链接明确是官方来源（.gov.cn、统计局、正规媒体）时。非官方来源且摘要已够用时不要抓取。
 5. **年份常识**：当年 GDP、人口等统计公报通常在次年 1-3 月才发布。用户问当年数据而公报未发布时，直接说明并给最近已发布年份的数据，不要反复搜索不存在的数据。
 ## 行政区划消歧与重名区县确认（必须遵守）
 中国存在多个重名区县。当用户查询数据、分析、制图、检索以下常见重名区县，且**未明确指定上级地级市或省份**时（如用户仅输入"鼓楼区"、"朝阳区"、"普陀区"、"西湖区"、"白云区"、"和平区"、"城关区"、"龙华区"、"宝山区"、"新华区"、"桥西区"）：
 - **严禁擅自推定或默认城市**：严禁自行主观推定为南京市鼓楼区、北京市朝阳区、上海市普陀区等任何默认城市！也不得在正文中直接输出默认城市的数据再附带问句。
 - **必须立刻调用 ask_user_choice 工具弹出交互式选项让用户选择目标城市**，禁止在用户选择前直接调用 search_web 或直接返回某默认城市的数据：
   - 常见候选对应：
     - "鼓楼区"：`[{"label": "江苏省南京市鼓楼区", "desc": "江苏省会核心区"}, {"label": "福建省福州市鼓楼区", "desc": "福建省会核心区"}, {"label": "江苏省徐州市鼓楼区", "desc": "徐州市主城区"}, {"label": "河南省开封市鼓楼区", "desc": "开封市古城区"}]`
     - "朝阳区"：`[{"label": "北京市朝阳区", "desc": "北京市CBD/中心区"}, {"label": "吉林省长春市朝阳区", "desc": "长春市核心主城区"}]`
     - "普陀区"：`[{"label": "上海市普陀区", "desc": "上海市中心城区"}, {"label": "浙江省舟山市普陀区", "desc": "舟山市普陀山风景区所在地"}]`
     - "西湖区"：`[{"label": "浙江省杭州市西湖区", "desc": "杭州市主城区"}, {"label": "江西省南昌市西湖区", "desc": "南昌市中心城区"}]`
     - "白云区"：`[{"label": "广东省广州市白云区", "desc": "广州市辖区"}, {"label": "贵州省贵阳市白云区", "desc": "贵阳市辖区"}]`
     - "和平区"：`[{"label": "天津市和平区", "desc": "天津市核心中心区"}, {"label": "辽宁省沈阳市和平区", "desc": "沈阳市主城区"}]`
     - "城关区"：`[{"label": "甘肃省兰州市城关区", "desc": "兰州市主城区"}, {"label": "西藏自治区拉萨市城关区", "desc": "拉萨市核心区"}]`
     - "龙华区"：`[{"label": "广东省深圳市龙华区", "desc": "深圳市辖区"}, {"label": "海南省海口市龙华区", "desc": "海口市核心区"}]`
     - "宝山区"：`[{"label": "上海市宝山区", "desc": "上海市辖区"}, {"label": "黑龙江省双鸭山市宝山区", "desc": "双鸭山市辖区"}]`
     - "新华区"：`[{"label": "河北省石家庄市新华区", "desc": "石家庄市辖区"}, {"label": "河北省沧州市新华区", "desc": "沧州市辖区"}, {"label": "河南省平顶山市新华区", "desc": "平顶山市辖区"}]`
     - "桥西区"：`[{"label": "河北省石家庄市桥西区", "desc": "石家庄市辖区"}, {"label": "河北省张家口市桥西区", "desc": "张家口市辖区"}]`
   - prompt 参数写明："全国有多个【{区名}】，请选择您要查询的具体行政区："
   - choice_key 参数设为："region_disambiguation"
 - 用户通过选项点击确定具体城市后，系统会在下一轮将用户选中的完整城市区名注入上下文，此时再进行数据检索、边界获取或专题图绘制。

 ## 数据下载的两阶段确认（必须遵守）
 当用户需要下载遥感影像、DEM、OSM 数据等需要外部数据源的数据时，必须分两步确认：
 1. **第一次弹选项（选数据源）**：调用 ask_user_choice 工具，弹出数据源列表。**第一个选项必须是"Esri 快速巡检（无需下载，免费瓦片，直接查看）"**，标注"立即可用"。其余选项标注配置状态（已配置/未配置）：地理空间数据云、Copernicus（哥白尼）、USGS EarthExplorer、NASA Earthdata、ASF（SAR数据）、OpenTopography（DEM）。prompt 写"请选择数据来源，Esri 快速巡检无需下载可直接使用"。
 2. **如果用户选择"Esri 快速巡检"**：直接调用 inspect_satellite_image 工具，传入 place_name 或 bbox，完成影像获取、RGB 启发式分类、结果图层注册。不要走下载流程，不要弹第二次选项。
 3. **用户选择其他数据源后**：从系统提示的"用户已做出的选择"中读取选中的数据源，用该数据源搜索可用数据。
 4. **第二次弹选项（选具体数据）**：搜索到多景/多个结果时，再次调用 ask_user_choice，选项包含关键信息（日期、云量、分辨率、传感器等），让用户选具体要下载哪一个。
 5. **用户选择后**：下载选中的数据并加载到地图，给出数据说明。
 - 未配置的数据源用户仍可选择，选择后提示"该数据源未配置，请在设置→连接器中添加账号"。
 - 不要跳过选项直接下载，也不要在一次回复里连续弹两次选项（必须等用户选完第一次再弹第二次）。
 - 如果只有一个数据源可用或只有一个搜索结果，直接说明并执行，不必弹选项。
 - 用户说"巡检卫星影像""快速查看卫星图""看看某区域卫星图"时，优先推荐 Esri 快速巡检选项。

 ## GIS 专业工作规范（必须遵守）

  ### 角色定位
  你不是普通的代码助手，而是具备 GIS 专业判断能力的空间分析助手。你的价值不仅在于调用工具，更在于：
  - 选择正确的分析方法（而非随便用一个工具）
  - 判断分析结果是否合理
  - 用专业语言解释结论和局限性

  ### 任务规划（复杂任务必须先规划）
  当用户请求涉及多步骤、多图层或多方法时（如选址分析、适宜性评价、灾害评估、多因子叠加），
  必须先在回复开头简要说明分析流程，再开始执行：
  1. 数据准备：需要哪些数据，是否已加载
  2. 数据检查：CRS 是否一致、几何是否有效、属性是否完整
  3. 方法选择：用什么分析方法，为什么选这个方法
  4. 工具调用：按流程逐步执行
  5. 结果验证：要素数、面积、空间位置是否合理
  6. 结果展示：符号化、图表、导出
  简单任务（单步操作、纯知识问答）不需要规划，直接执行即可。

  ### 方法选择决策树
- **地铁线路**用 metro_line（展示长沙/北京等城市任意线路与站点，支持全城线网；用户提到"地铁/线路/站点图"时优先此工具）
  - 算面积/距离前：检查 CRS，WGS84 经纬度必须先投影（measure_area/measure_distance 已自动处理，自定义代码需注意）
  - 缓冲区分析：经纬度下做缓冲会变形，unit=m 时工具内部自动投影
  - 空间连接：predicate 默认用 intersects，严格包含用 within，找相邻用 touches
  - 叠置分析：求共同区域用 intersect，合并用 union，去掉部分用 difference，截取用 clip
  - 插值：点密集用 IDW，需要平滑用 RBF，需要误差估计用克里金（execute_python）
  - 分类：有训练样本用 RandomForest，无样本用 KMeans，单指数提取用阈值分割
  - 属性连接 vs 空间连接：按属性字段（key）连接用 join_field；按空间关系（predicate）连接才用 spatial_join（最易选错）
  - 重分类优先用 raster_reclassify；只有需要多波段任意表达式时才用 raster_calculator
  - surface_volumes 需要两个同网格的 DEM，或一个 DEM + 参考高程；网格不一致会明确失败
  - cost_distance / least_cost_path 是栅格代价面，不是路网；路网分析用 network_analysis / od_cost_matrix
  - spatial_regression 是探索性回归（OLS + 残差自相关），要求因变量和自变量都是数值字段
  - geometry_attributes 在经纬度坐标系下面积/长度无意义，工具会自动投影并在结果中说明
  - spatial_weights_matrix 可独立生成并查看/下载权重文件；spatial_moran / spatial_hotspot / spatial_regression 当前各自构建权重，不读取此文件
  - 不确定用什么方法时：参考已加载的 GIS 专业知识库（knowledge/ 模块）中的"方法选择依据"

  ### 结果验证清单（分析完成后必须自查）
  1. 输出图层的要素数是否合理（与输入对比，不应暴增或暴减）
  2. 面积/距离数值是否在合理范围（如城市级面积应为平方公里级，不应是平方米级或平方度）
  3. 空间位置是否正确（结果应在研究区内，不应飞到别处）
  4. 统计结果是否有异常值（如均值远超最大值）
  5. 拓扑是否有效（面图层无自相交、无重叠）
  发现异常时主动说明，不要把错误结果当正确结论交付。

  ### 结果解释要求
  分析完成后，回复中必须包含：
  - 关键统计数字（如"缓冲区覆盖了 XX 个 POI，占总数的 XX%"）
  - 空间分布特征（如"高值区主要集中在东部沿海"）
  - 方法和参数说明（如"使用 DBSCAN 聚类，eps=0.01，min_samples=3"）
  - 局限性说明（如"数据仅覆盖主城区，乡村区域未包含"或"权重为主观设定，建议做敏感性分析"）
  不要只返回原始数据或说"已完成"，要给出专业解读。

 ### 国外地点
  - 国外边界调用 fetch_osm_boundary_or_features(query="国家或地区", feature_type="boundary")；execute_python 沙箱禁止用户代码联网导入 requests/urllib，禁止在被拦截后改用内省或其他导入方式绕过。
  - 搜索国外内容时用当地语言和英文搜关键词
  - 不要用高德 POI 搜索国外地点（只覆盖中国）

 """


# ===== GLM 免费模型提示词（支持工具调用） =====
SYSTEM_PROMPT_GLM = """你是 GIS WorkTable 的 AI 助手（免费模型）。

## 你能做的事
1. **回答 GIS 知识问题**：地理信息、坐标系、空间分析、地图学等任何相关问题
2. **调工具做 GIS 操作**：搜索网页、获取边界、查找 AOI、保存文件、执行 Python 等
3. **设计 workflow**：用户说一个任务，你帮他把步骤拆清楚然后逐步执行
4. **文本处理**：整理数据、格式化输出、写报告

## 回复风格
 - 中文为主，纯文本，不用 markdown 格式符号，不用表情
 - 列出步骤时分点清晰
 - 不确定的直说不知道

## 安全红线
 - 不提供敏感地理坐标（军事基地等）
 - 行政区划遵守中国官方标准

## 核心规则
 - 用户提出复杂需求时，先总结成清晰的工作流，然后分步使用工具处理
 - 工作流未完成时不允许直接结束，该用工具时必须用
 - 每执行完一步，清晰知道下一步该做什么，并做出正确决策
 - 审核工作流每一步的结果，确保正确性
 - **当用户要求获取数据、加载图层、画图时，必须在同一次回复中完成所有工具调用，不要分两轮**（前端只保留最后一轮数据）
 - 需要多个省的数据时一次性调多次 datav_boundary，不要分批
 - 需要同时画线和加载边界，一次性调完所有工具
 - **交付红线**：严禁自称“无法生成PNG图片”（平台支持 execute_python/matplotlib 输出 PNG，前端会自动识别并展示）；严禁在正文输出裸 <svg> 代码让用户保存；严禁向用户索要本地 shp/geojson 路径（国内边界一律用 datav_boundary 内置数据）；必须在地图上展示边界并交付图件。

## 工具使用优先级
  - 空间分析工具按算法复用，不按业务对象（如医院、麦当劳）分别造工具；先用 get_registered_layers 确认实际图层，再将业务名称作为图层选择或属性筛选条件传给已有工具。只有系统尚不支持的分析动作才需要新增算法能力。
  - 优先使用专用工具（amap_geocode / amap_poi_search / datav_boundary / network_analysis / measure_area / measure_distance 等），execute_python 是最后选择
  - POI 搜索采用多源兜底：国外优先 OSM；国内高德缺失或失败时自动回退到公开 OSM/Overpass 来源，并在结果中说明数据源与覆盖限制。
  - 同一图层或两个图层之间最近的一对要素必须调用 nearest_pair；先读当前注册图层摘要和属性样例，仍无法判断对象在哪个图层时调用 get_registered_layers(keyword="对象名") 搜索属性内容。跨图层传 layer_name 和 target_layer，同层留空 target_layer；限定类别或名称时分别传 feature_filter、target_filter。不得为具体对象创建专用工具、用 get_layer_detail 的前三条预览代替全量检索，或编造未注册图层。
  - 栅格/矢量/统计优先用专用工具：raster_reclassify / raster_focal_stats / euclidean_distance / raster_extract_by_mask / surface_volumes / join_field / geometry_attributes / minimum_bounding_geometry / points_to_line / generate_points_along_lines / spatial_weights_matrix / spatial_regression / directional_distribution / central_tendency / od_cost_matrix / feature_to_raster / raster_to_feature / create_fishnet / cost_distance / least_cost_path
  - 属性字段连接用 join_field，空间关系连接用 spatial_join；重分类用 raster_reclassify；代价面用 cost_distance / least_cost_path，路网用 network_analysis / od_cost_matrix
  - 计算图层面积必须直接调用 measure_area 工具，测距调用 measure_distance；严禁只口头输出“请稍等/我来调用工具”而不真实调用工具
  - 有专用工具的操作不得用 execute_python 代替
  - execute_python 中禁止硬编码 API Key
  - **execute_python 批量执行规范**：当需要生成多张图片/图表时，**必须在一次 execute_python 调用中完成所有图表生成**（使用 plt.subplot 或多次 plt.savefig），不要为每张图片单独调用 execute_python。单独调用会触发过热保护（上限20次/请求）。
  - **严禁在最终回复里粘贴你已经执行过的源码**（复述也不行）：代码跑完后只是执行细节，不是交付物，正文只写"做了什么→结果是什么→结论是什么"；只有用户明确索要代码时才展示源码。
  - **图表/地图制图规范（强制执行）**：使用 matplotlib 生成任何图表或地图时：**中文字体不许重置**（严禁 `plt.rcdefaults()`/`plt.style.use()` 或改写 `font.*`，否则中文全变方框）；①标题明确规范（无多余废话）；②必须带标准图例或色条（注明指标与单位），遥感分类图必须标明类别对应颜色；③**注记严禁相互堆叠重叠**：长三角、珠三角等密集区域必须使用 `adjustText`（已预装：`from adjustText import adjust_text; adjust_text(texts, arrowprops=dict(arrowstyle='->', color='#666', lw=0.6))`）或引出线避让，文字简练（如“上海\n4.7万亿”），边框浅灰细线，严禁挤成黑块；④保存必须用 `bbox_inches='tight', dpi=150`。生成后在回复中说明主要图例与结论。

  - **专题地图与卫星底图**：交互地图先把图层渲染到现有 Leaflet 地图，卫星影像来自当前地图底图服务，不要让 matplotlib/execute_python 去下载瓦片或拼接卫星影像。用户明确要求图片时调用 export_map 导出当前地图（保留当前底图与图层）；要求 PDF/比例尺/经纬网/指北针/旋转时调用 export_pdf。execute_python 生成的是独立图表/静态矢量图，不含当前交互地图底图；不要把它说成卫星专题地图。
  - **引用历史任务继续修改**：收到带有 task_id 的引用回复时，优先读取该任务注入的代码、图层和文件产物，在那份任务上继续修改；不得只凭聊天文字猜测旧结果，也不得混用其他任务的数据。
  - **任务引用与继续修改**：如果当前消息引用了旧回复并附带历史任务上下文，先读取其中 task_id、代码、图层与产物记录，在该任务上继续修改；不要只依赖聊天文字猜测旧文件或结果。若引用上下文没有可用任务记录，则说明无法定位的具体产物。

每个工具的具体使用规则（参数、约束、最佳实践）见各工具的 description，不必事先记忆。

## 多轮上下文继承与选项决策规则（必须遵守）
1. **多轮上下文继承**：用户说“需要专题图”、“做成图”、“在地图上展示”等简短需求时，必须直接继承上一轮确定的地理对象（如南京市鼓楼区）、年份（如2025年）、指标（如GDP数值），调用工具必须传完整实体全称，严禁退化为模糊词，严禁主动把单区膨胀为多地对比。
2. **行动优先，杜绝盘问**：优先使用合理默认值直接出图交付成果。严禁在正文中让用户打字回复（如“你回一句方案A我就出图”），严禁抛出问卷式选项；确需用户决策且无法推断时，只能调用 ask_user_choice 按钮单次询问。
3. **行政区划消歧**：仅在首轮未指明上级城市且无任何上下文时，调用 ask_user_choice 弹按钮消歧。下一轮选定后直接沿用，不得反复追问。

"""


# ============================================================
# 对话历史存储（文件持久化）
# ============================================================

conversation_history = {}
_HISTORY_LOCK = threading.RLock()
_HISTORY_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "cache", "history")


class _PendingHistory(list):
    """Request-local history view rebased against committed session history."""

    def __init__(self, messages, base_history):
        super().__init__(messages)
        self.base_history = base_history


def _rebase_history_context(session_id: str, context: list) -> list:
    if not isinstance(context, _PendingHistory):
        return context
    with _HISTORY_LOCK:
        current = conversation_history.get(session_id)
        if current is context.base_history:
            return context
        request_entry = next(
            (item for item in reversed(context) if isinstance(item, dict) and item.get("role") == "user"),
            None,
        )
        if request_entry is None:
            return context
        messages = list(current or [])
        if messages and not _check_topic_relevance(request_entry.get("content", ""), messages):
            messages = []
        rebased = _PendingHistory(messages + [request_entry], current)
        return rebased


def _ensure_history_dir():
    os.makedirs(_HISTORY_DIR, exist_ok=True)


# session_id 白名单清洗：只保留字母/数字/下划线/连字符，其余替换为 _。
# 防止前端传入 ../../xxx 等路径片段污染 history/缓存目录（写文件路径均经此函数）。
_SESSION_ID_RE = None

def _sanitize_session_id(session_id: str) -> str:
    global _SESSION_ID_RE
    if not session_id:
        return "default"
    if _SESSION_ID_RE is None:
        import re as _re_mod
        _SESSION_ID_RE = _re_mod.compile(r'[^a-zA-Z0-9_\-]')
    sid = _SESSION_ID_RE.sub('_', str(session_id))[:80]
    return sid or "default"

def _history_path(session_id: str) -> str:
    return os.path.join(_HISTORY_DIR, f"session_{_sanitize_session_id(session_id)}.json")


def _sanitize_history(history: list) -> list:
    """清洗历史记录，确保每条消息格式符合 API 要求"""
    sanitized = []
    for i, msg in enumerate(history):
        if not isinstance(msg, dict):
            print(f"[GIS] 警告: 历史记录第 {i} 条格式异常，已跳过 (type={type(msg).__name__})", flush=True)
            continue
        role = msg.get("role", "user")
        new_msg = {"role": role}
        new_msg["content"] = msg.get("content")
        if role == "assistant" and isinstance(new_msg["content"], str):
            new_msg["content"] = _strip_protocol_text(new_msg["content"])
        if role == "assistant" and isinstance(msg.get("reasoning_content"), str):
            new_msg["reasoning_content"] = msg["reasoning_content"]
        if role == "tool":
            new_msg["tool_call_id"] = msg.get("tool_call_id", "")
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            new_msg["tool_calls"] = [
                {
                    "id": tc.get("id"),
                    "type": tc.get("type", "function"),
                    "function": tc.get("function", {"name": "", "arguments": "{}"}),
                }
                for tc in tool_calls if isinstance(tc, dict)
            ]
        sanitized.append(new_msg)
    return sanitized


def _load_history(session_id: str) -> list:
    path = _history_path(session_id)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return _sanitize_history(json.load(f))
        except Exception:
            pass
    return []


def _save_history(session_id: str, history: list):
    _ensure_history_dir()
    path = _history_path(session_id)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _strip_protocol_text(text: str) -> str:
    """清洗 assistant 内容里泄漏的工具调用协议原文（DSML/tool_call 等）。

    泄漏一旦写进历史会形成反馈循环：下一轮模型在上下文里看到自己输出过的
    协议原文，就会继续模仿该格式把工具调用当正文输出 → 工具不再执行、
    协议文本直接漏给用户。所以在【写入历史前】与【读出历史时】双向清洗。

    实现采用逐行状态机 + 兜底标签删除，不依赖开/闭标签正确配对
    （模型输出常有缺斜杠、块交错等畸形，纯正则配对会漏）。
    """
    if not text:
        return text
    if "DSML" not in text and "<tool_call" not in text and "```tool_call" not in text:
        return text

    import re as _re
    cleaned = text
    # 1) 成对/跨行协议块整段删除（非贪婪、允许畸形标签；未闭合则删到文末）
    cleaned = _re.sub(r'<[|\s｜]*DSML.*?(?:</[|\s｜]*DSML[^>]*>|\Z)', '', cleaned, flags=_re.DOTALL)
    # 2) 残余的孤立/畸形 DSML 标签 token
    cleaned = _re.sub(r'</?[|\s｜]*DSML[|\s｜]*[^>]*>', '', cleaned)
    # 其余协议标记
    cleaned = _re.sub(r'<tool_call>.*?</tool_call>', '', cleaned, flags=_re.DOTALL)
    cleaned = _re.sub(r'</?tool_call>', '', cleaned)
    cleaned = _re.sub(r'```tool_call.*?```', '', cleaned, flags=_re.DOTALL)
    cleaned = _re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def commit_assistant_reply(
    session_id: str, response: str, reasoning: str = None,
    history_context: list = None,
):
    """把一轮 AI 回复写回会话历史并落盘（幂等：末条已是 assistant 则跳过）。

    普通 /api/chat 与 SSE /api/chat/stream 共用，保证两种入口的对话历史一致：
    stream 之前只 append 用户消息、从不写回 AI 回复，导致下一轮模型看不到
    上一轮 AI 说了什么（“回复继续即可加载”这类状态随之丢失）。
    """
    if not response or not response.strip():
        return
    with _HISTORY_LOCK:
        current_history = conversation_history.get(session_id)
        if history_context is not None:
            if (current_history is history_context and history_context
                    and history_context[-1].get("role") == "assistant"):
                return  # 同一上下文已经提交
            history = _rebase_history_context(session_id, history_context)
            conversation_history[session_id] = history
        else:
            history = current_history
            if history is None:
                history = _load_history(session_id)
                conversation_history[session_id] = history
        if history and history[-1].get("role") == "assistant":
            return  # 已提交过，防重复
        response = _strip_protocol_text(response)
        entry = {"role": "assistant", "content": response}
        if reasoning:
            entry["reasoning_content"] = reasoning
        history.append(entry)
        if len(history) > _MAX_HISTORY:
            history = history[-_MAX_HISTORY:]
            conversation_history[session_id] = history
        _save_history(session_id, history)


def _clean_old_history(max_days: int = 7):
    """删除超过 max_days 的历史文件"""
    import time as time_module
    now = time_module.time()
    cutoff = now - max_days * 86400
    if not os.path.isdir(_HISTORY_DIR):
        return
    for fname in os.listdir(_HISTORY_DIR):
        if fname.startswith("session_") and fname.endswith(".json"):
            fpath = os.path.join(_HISTORY_DIR, fname)
            try:
                mtime = os.path.getmtime(fpath)
                if mtime < cutoff:
                    os.remove(fpath)
            except Exception:
                pass


# ============================================================
# 说明：API Key 兜底逻辑已移除
# ============================================================

# Key 只由前端 localStorage 里的 Provider 列表随每次请求经 llm_config 携带，
# 后端不再读 apikey.txt / glm_apikey.txt，也不再有 _get_default_key/_get_default_glm_key。
# 需要兜底时用 backend.services.llm_config.resolve_llm_config() 把旧 provider
# 字符串翻译成内置默认 cfg。


# ============================================================
# 缓存清理
# ============================================================

def clean_old_cache(max_age_days: int = 7):
    """清理超过 max_age_days 天的缓存文件"""
    now = time.time()
    max_age = max_age_days * 86400
    removed = 0
    _CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "cache", "aoi")

    if os.path.isdir(_CACHE_DIR):
        for fname in os.listdir(_CACHE_DIR):
            if not fname.endswith('.json'):
                continue
            if not fname.startswith(('bd_search_', 'gd_search_')):
                continue
            fpath = os.path.join(_CACHE_DIR, fname)
            try:
                if now - os.path.getmtime(fpath) > max_age:
                    os.remove(fpath)
                    removed += 1
            except Exception:
                pass

    return removed


# ============================================================
# 辅助函数：消息构建（供普通调用和 SSE 流式调用复用）
# ============================================================

# 历史记录最大长度
_MAX_HISTORY = 30

def _get_or_create_history(session_id: str, message: str) -> list:
    """获取或创建会话历史，含话题切换检测"""
    with _HISTORY_LOCK:
        if session_id not in conversation_history:
            conversation_history[session_id] = _load_history(session_id)
        base_history = conversation_history[session_id]
        history = list(base_history)
        # 话题切换检测
        if history:
            topic_related = _check_topic_relevance(message, history)
            if not topic_related:
                history = []
        # 新用户消息仅进入本次上下文；AI 成功回复后才提交为正式历史。
        history.append({"role": "user", "content": message})
        return _PendingHistory(history, base_history)


def _build_system_content(cfg, message: str, session_id: str = "default", force_skills: list = None,
                          task_id: str = None) -> tuple:
    """构建 system prompt，返回 (system_content, skill_text, model_display)

    cfg: LLMConfig
      - cfg.glm_prompt True → 用 GLM 专属前缀，否则通用 SYSTEM_PROMPT
      - cfg.router    True → 先用当前模型跑一次技能路由
      - model_display 显示 cfg.model

    KV 缓存友好设计：
    - SYSTEM_PROMPT / SYSTEM_PROMPT_GLM 是固定前缀（永远不变）
    - 所有可变部分（时间、模型名、技能）统一追加到末尾
    - 这样 API 服务端可以命中前缀 KV 缓存，首 token 时间从 10-30s 降到 0.5-1s
    """
    now = datetime.datetime.now().astimezone()

    # 固定前缀（永远不变 → KV cache 命中）
    if cfg.glm_prompt:
        system_content = SYSTEM_PROMPT_GLM
    else:
        system_content = SYSTEM_PROMPT
    model_display = cfg.model

    # === 可变后缀（每次追加在末尾，不影响前缀缓存） ===
    appendix_parts = []

    # 当前模型名
    appendix_parts.append(f"当前运行模型：{model_display}")

    # 当前时间
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    tz_str = now.tzname() or 'UTC'
    appendix_parts.append(f"当前时间：{now_str} ({tz_str})")
    appendix_parts.append("注意：根据当前时间判断数据的时效性")

    # 技能路由：cfg.router 开启时，用当前选中模型跑一次（同模型同 key，
    # 低温 + 关 reasoning，保证返回纯 JSON 技能数组）
    all_skills = []
    if getattr(cfg, "router", False):
        routed_skills = _route_skills(message, cfg)
        if routed_skills:
            all_skills.extend(routed_skills)
    # 简短样式修改常不含“地图/专题图”等完整任务词，按明确的制图意图直接注入已维护的制图知识。
    if _is_cartography_request(message) and "cartography" not in all_skills:
        all_skills.append("cartography")
    if force_skills:
        for s in force_skills:
            if s not in all_skills:
                all_skills.append(s)

    skill_text = ""
    if all_skills:
        skill_text = _read_skill_files(all_skills)
        if skill_text:
            appendix_parts.append(f"## 参考技能文档\n{skill_text}")

    # 待确认选项的用户选择结果（choose_option 动作中用户已选的项）
    try:
        from backend.services import pending_action as _pa_ctx
        _pending_act = _pa_ctx.get_pending_action(session_id)
        if _pending_act and _pending_act.get("action") == "choose_option" and _pending_act.get("selected"):
            _sel = _pending_act["selected"]
            _ck = _pending_act.get("choice_key", "")
            _sel_value = _sel.get('value', '')
            appendix_parts.append(
                f"## 用户已做出的选择\n"
                f"选择类别：{_ck}\n"
                f"用户选择：{_sel.get('label', '')}" +
                (f"（选项标识：{_sel_value}）" if _sel_value else "") +
                (f"（{_sel.get('desc')}）" if _sel.get('desc') else "") +
                "\n请基于此选择继续执行，不要再次询问用户选什么。"
                + ("\n注意：选项标识为 esri_quick_inspect 时，直接调用 inspect_satellite_image 工具，不要再走数据下载流程。" if _sel_value == "esri_quick_inspect" else "")
            )
    except Exception:
        pass

    # 当前已注册的图层信息（让 AI 知道已有图层，避免重复下载）
    try:
        from backend.services.tools import get_registered_layers_snapshot
        _snap = get_registered_layers_snapshot()
        if _snap:
            _layer_lines = []
            for _lyr in _snap:
                _typ = ", ".join(_lyr.get("geometry_types", []))
                _cnt = _lyr.get("feature_count", 0)
                _box = _lyr.get("bbox", [])
                _ext = ""
                if _box and len(_box) == 4 and _box != [0,0,0,0]:
                    _lng = (_box[0] + _box[2]) / 2
                    _lat = (_box[1] + _box[3]) / 2
                    _ext = f"（中心 {_lat:.3f}°N, {_lng:.3f}°E）"
                # 提取属性字段（从 geojson 中）
                _fields = set()
                _geojson = _lyr.get("geojson", {})
                if _geojson:
                    for _f in _geojson.get("features", [])[:30]:
                        _fields.update((_f.get("properties", {}) or {}).keys())
                _fields_str = ""
                if _fields:
                    _fields_str = f"，字段：{', '.join(sorted(_fields)[:8])}"
                    if len(_fields) > 8:
                        _fields_str += f" 等{len(_fields)}个"
                _examples = _lyr.get("property_examples", [])
                _examples_str = f"，属性样例：{_examples}" if _examples else ""
                _lyr_name = _lyr.get('filename') or _lyr.get('name', '未知')
                _layer_lines.append(f"  - {_lyr_name}：{_cnt} 个 {_typ}{_ext}{_fields_str}{_examples_str}")
            appendix_parts.append("## 当前已加载的图层\n" + "\n".join(_layer_lines) +
                "\n重要：如果已有图层，优先使用现有图层做分析，严禁重复下载。"
                "\n需要按医院、麦当劳等对象定位图层时，先根据图层名、字段与属性样例判断；样例不足时用 get_registered_layers(keyword=...) 在注册要素属性中检索，再将匹配结果用于通用空间分析工具。"
                "\n提示：当用户询问当前有几个图层、图层有几个要素/东西、图层内容时，直接清晰列出图层及要素数量并给出概览；若需最新动态信息或图层有变更，可主动调用 get_registered_layers 或 list_layers 工具，绝不能回答没有拿到图层实时数据。")
        else:
            appendix_parts.append("## 当前已加载的图层\n当前地图尚未注册任何图层。如果用户询问图层或要求处理图层，可提醒用户先在工作区导入数据或在地图上绘制图层；亦可调用 get_registered_layers 工具实时确认。")
    except Exception:
        pass

    # === Task Manager: 注入任务工作上下文（最新代码 + Artifact + 执行历史） ===
    # 注意：必须按 session 查任务，不能用全局 get_current_task_id()。
    # 请求管线里 set_current_task 要等到 run_agent/run_agent_stream 内部才执行，
    # 构建本条 system prompt 时全局值还是「上一个请求（可能是别的会话）」的任务——
    # 新会话第一条消息会被注入旧会话的任务目标/上一轮源码/执行历史，
    # 模型直接把旧话题（如广东GDP排名）当作当前任务复述 → 跨会话幻觉污染。
    try:
        from backend.services.task_manager import find_active_task_for_session, build_task_context, get_task
        _referenced_task = get_task(str(task_id)) if task_id else None
        _tid = (str(task_id) if _referenced_task else None) if task_id else find_active_task_for_session(session_id)
        if task_id and not _referenced_task:
            appendix_parts.append("## 历史任务引用不可用\n用户引用的 GIS 任务记录已不存在或已删除。不要把当前会话的其他任务当成该任务继续修改；请说明无法定位原任务产物。")
        if _tid:
            _task_ctx = build_task_context(_tid)
            if _task_ctx:
                if task_id and _tid == str(task_id):
                    appendix_parts.append("## 用户明确引用的历史 GIS 任务\n以下代码、图层与产物属于用户引用的任务。用户要求修改或继续时，先基于这些真实记录操作；不得把其他任务的结果混入。")
                appendix_parts.append(_task_ctx)
    except Exception:
        pass

    # 用分隔线连接可变部分（清晰的分界，不影响前缀缓存）
    if appendix_parts:
        system_content += "\n\n---\n" + "\n\n".join(appendix_parts)

    return system_content, skill_text, model_display


def _build_langgraph_messages(system_content: str, history: list) -> list:
    """将 system_content + 历史记录转为 LangChain BaseMessage 列表

    assistant 历史一并带回（含 reasoning_content），便于 GLM 思考模型跨请求
    续推时由 ReasoningChatOpenAI 适配层把思考内容原样塞回 assistant 消息体。
    """
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
    messages = [SystemMessage(content=system_content)]
    for msg in history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            messages.append(SystemMessage(content=content or ""))
        elif role == "user":
            messages.append(HumanMessage(content=content or ""))
        elif role == "assistant":
            content = content or ""
            if not content:
                continue
            akw = {}
            rc = msg.get("reasoning_content")
            if isinstance(rc, str) and rc:
                akw["reasoning_content"] = rc
            messages.append(AIMessage(content=content, additional_kwargs=akw))
    return messages


# ============================================================
# 确定性短指令：pending task 的“继续/确认/执行/取消”
# ============================================================

def _try_handle_confirm_command(session_id: str, message: str) -> dict | None:
    """若存在 pending task 且消息是“继续/确认/执行/取消”类短指令，则确定性处理。

    返回兼容 chat result 的 dict（已写回本轮历史、已消费/清除 pending）；
    未命中（无 pending / 不是短指令 / 动作不可执行）返回 None → 走正常 AI 流程。
    """
    from backend.services import pending_action

    # choose_option：用户消息匹配某个选项时，记录选择并走正常 AI 流程
    action = pending_action.get_pending_action(session_id)
    cmd = pending_action.classify_short_command(message)
    if action and action.get("action") == "choose_option" and cmd != "cancel":
        options = action.get("options", [])
        msg_norm = (message or "").strip()
        for opt in options:
            label = (opt.get("label") or "").strip()
            value = (opt.get("value") or "").strip()
            if label and (msg_norm == label or msg_norm == value or
                          msg_norm.startswith(label) or label in msg_norm):
                action["selected"] = opt
                pending_action.set_pending_action(session_id, action)
                return None  # 走正常 AI 流程，AI 从上下文看到选择后继续
        # 用户输入了非选项内容，清除 pending 让 AI 自由处理
        pending_action.clear_pending_action(session_id)
        return None

    if cmd is None:
        return None
    if action is None:
        return None  # 没有 pending：短指令也交给正常 AI（测试 3 语义）

    if cmd == "continue":
        result = pending_action.run_action(action)
        if result is None:  # 未知/不支持的动作 → 不清除 pending，交回 LLM
            return None
    else:  # cancel
        result = {
            "response": f"已取消：{action.get('summary') or '待处理任务'}（未加载到地图）。",
            "reasoning": None,
            "layers": [],
            "images": [],
            "heatmap": None,
            "clear_layers": False,
            "layer_ops": [],
            "pending_suggestions": None,
        }

    # 本轮对话写回（user 已在此追加；补 assistant 并落盘），然后消费 pending
    history_context = _get_or_create_history(session_id, message)
    commit_assistant_reply(
        session_id, result.get("response", ""), None,
        history_context=history_context,
    )
    pending_action.clear_pending_action(session_id)
    return result


# ============================================================
# 主入口: chat_with_ai（重构后使用 LangGraph Agent）
# ============================================================

def chat_with_ai(message: str, session_id: str = "default", cfg=None,
                 force_skills: list = None, amap_key: str = None,
                 provider: str = "", mode: str = "full", task_id: str = None) -> dict:
    """
    调用 AI 进行对话（使用 LangGraph Agent）

    Args:
        message: 用户消息
        session_id: 会话 ID
        cfg: LLMConfig（必填）。模型构造 / system prompt / 技能路由 / reasoning
             全部由这份配置决定，不再按 provider 名硬编码分支。
        force_skills: 用户通过 chip 标签指定的技能
        amap_key: 高德地图 Web API Key
        provider: 旧 provider 名，仅用于日志 / 工程存档展示，不参与调用逻辑

    返回 dict:
        {
            "response": str,           # AI 回复文本
            "reasoning": str|None,     # 思考过程（reasoning 开启时有）
            "layers": [...],           # 待加载图层列表
            "images": [...],           # 生成的图表
            "heatmap": {...} | None,   # 热力图数据
            "clear_layers": bool,      # 是否清空地图
            "pending_suggestions": {...} | None,  # AOI 候选
        }
    """
    if cfg is None:
        raise ValueError("chat_with_ai 需要 LLMConfig（cfg），请先 resolve_llm_config()")

    # 模式已固定为完整模式，快速模式已移除

    # 自动清理过期缓存
    clean_old_cache(7)

    # 确定性短指令：存在 pending task 时，“继续/确认/执行/取消”不走 LLM
    handled = _try_handle_confirm_command(session_id, message)
    if handled is not None:
        return handled
    from backend.services import pending_action as _pa
    # choose_option 上下文回填：用户点击选项后只发短 label，把原任务拼回（防地名幻觉）
    # 必须在 clear_pending_action 之前取值
    _ctx_backfill = _pa.build_choice_backfill(session_id, message)

    # 走正常 AI：先清掉上一轮遗留的 pending（若本轮有新的“就绪未展示”图层，
    # 会在 Agent 结束时由 auto-promote 重新挂起）
    _pa.clear_pending_action(session_id)

    if _ctx_backfill:
        message = _ctx_backfill

    # 获取或创建历史记录
    history = _get_or_create_history(session_id, message)

    system_content, skill_text, model_display = _build_system_content(cfg, message, session_id, force_skills, task_id)

    # 构建消息列表（LangGraph 用 BaseMessage 格式，assistant + reasoning 一并带回）
    history = _rebase_history_context(session_id, history)
    langgraph_messages = _build_langgraph_messages(system_content, history)

    # === 调用 LangGraph Agent ===
    from backend.services.graph import run_agent

    start_time = time.time()
    print(f"[GIS] [{model_display}] 启动 LangGraph Agent...", flush=True)

    result = run_agent(
        messages=langgraph_messages,
        cfg=cfg,
        amap_key=amap_key or "",
        skill_text=skill_text,
        original_message=message,
        session_id=session_id,
        task_id=task_id,
    )

    elapsed = time.time() - start_time
    print(f"[GIS] [{model_display}] LangGraph Agent 完成，耗时 {elapsed:.1f}s", flush=True)

    # 写回本轮 AI 回复到历史并落盘（与 SSE 流共用同一函数）
    ai_reply = result.get("response", "")
    if result.get("busy"):
        # 用户消息尚未提交；busy 结果不能替换或污染正式历史。
        print("[GIS] 会话忙，本轮不写入会话历史", flush=True)
        return result
    else:
        commit_assistant_reply(
            session_id, ai_reply, result.get("reasoning"), history_context=history,
        )

    # 定期清理过期历史文件
    if len(conversation_history) > 100:
        _clean_old_history(7)

    # 记录日志
    try:
        from backend.services.log_service import log_turn
        from backend.services.tools import _registered_layers
        log_turn(
            session_id=session_id,
            user_message=message,
            ai_reply=ai_reply,
            layers_snapshot=dict(_registered_layers),
            saved_files=None,
        )
    except Exception:
        pass

    # 自动保存工程快照（不阻塞主流程）
    try:
        from backend.services.project_service import auto_save
        map_state = {}
        auto_save(
            session_id=session_id,
            provider=provider or cfg.model,
            map_state=map_state,
        )
    except Exception:
        pass

    return result


# ============================================================
# 清除记忆
# ============================================================

def clear_memory(session_id: str = "default"):
    """清除指定会话的记忆"""
    from backend.services.tools import acquire_shared_state_lock, release_shared_state_lock
    if not acquire_shared_state_lock(0):
        return False
    try:
        path = _history_path(session_id)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        if session_id in conversation_history:
            conversation_history[session_id] = []
        # 清除待确认的 pending task
        try:
            from backend.services import pending_action
            pending_action.clear_pending_action(session_id)
        except Exception:
            pass
        # 清除注册的图层和所有共享状态
        try:
            from backend.services.tools import (
                _registered_layers, _pending_layers, _pending_images,
                _pending_layer_ops, _state_lock, reset_state, get_current_task_id,
            )
            # 先删除 task_manager 中的当前任务（磁盘文件 + 内存），避免旧任务上下文残留
            try:
                _tid = get_current_task_id()
                if _tid:
                    from backend.services.task_manager import delete_task
                    delete_task(_tid)
            except Exception:
                pass
            with _state_lock:
                _registered_layers.clear()
                _pending_layers.clear()
                _pending_images.clear()
                _pending_layer_ops.clear()
                # 重置当前任务 ID，避免 system prompt 注入旧任务上下文（代码/Artifact/执行历史）
                reset_state()
        except Exception:
            pass
        try:
            from backend.services.log_service import archive_temp_to_perm
            archive_temp_to_perm(session_id)
        except Exception:
            pass
        return True
    finally:
        release_shared_state_lock()


# ============================================================
# 取消 AI 请求（按 session 隔离，避免并发会话互相误伤）
# ============================================================

# 全局取消使用代次：已运行会话保留旧代次并被取消；新请求记录当前代次后可正常运行。
_global_cancel_generation = 0
_session_cancel_generation: dict = {}
_cancelled_sessions: dict = {}
_CANCELLED_SESSIONS_MAX = 1000
_CANCEL_LOCK = threading.Lock()

def request_cancel(session_id: str = ""):
    """标记取消指定会话的 AI 请求（由 /api/cancel 端点调用）。

    session_id 为空时视为"全局取消"（兼容旧前端：取消所有正在跑的会话）。
    """
    global _global_cancel_generation
    if not session_id:
        # 兼容模式：全局取消
        with _CANCEL_LOCK:
            _global_cancel_generation += 1
        print("[GIS] 用户请求取消（全局），已设置取消标志", flush=True)
        return "已发送取消信号"
    with _CANCEL_LOCK:
        if session_id not in _cancelled_sessions:
            while len(_cancelled_sessions) >= _CANCELLED_SESSIONS_MAX:
                _cancelled_sessions.pop(next(iter(_cancelled_sessions)))
        _cancelled_sessions[session_id] = True
    print(f"[GIS] 用户请求取消，已标记会话 {session_id} 的取消标志", flush=True)
    return f"已发送取消信号（会话 {session_id}）"

def is_session_cancelled(session_id: str) -> bool:
    """检查指定会话是否被取消（同时兼容全局标志）。"""
    with _CANCEL_LOCK:
        started_generation = _session_cancel_generation.get(session_id, _global_cancel_generation)
        return (started_generation < _global_cancel_generation
                or bool(_cancelled_sessions.get(session_id)))

def clear_session_cancel(session_id: str):
    """请求开始时清除本会话的取消标记（不动其他会话）。"""
    with _CANCEL_LOCK:
        _cancelled_sessions.pop(session_id, None)
        if session_id not in _session_cancel_generation:
            while len(_session_cancel_generation) >= _CANCELLED_SESSIONS_MAX:
                _session_cancel_generation.pop(next(iter(_session_cancel_generation)))
        _session_cancel_generation[session_id] = _global_cancel_generation


# ============================================================
# 测试 LLM 连接（通用 /api/test-key）
# ============================================================

def _http_request_ctx(e: Exception) -> Optional[str]:
    """从 SDK 抛出的 HTTP 异常链里取出「实际发出的请求」上下文。

    只读异常对象上的 request.method / request.url / status_code，不碰
    header/body；URL 中的用户信息、查询参数和片段也会被移除。作用：把 405/404
    这类「请求到了哪个主机/路径、服务器回了什么状态码」暴露给用户，方便核对接口。
    返回形如 “POST http://host/v1/chat/completions → HTTP 405”。
    """
    cur = e
    seen = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        resp = getattr(cur, "response", None)
        status = getattr(cur, "status_code", None)
        req = getattr(resp, "request", None) if resp is not None else None
        if req is not None:
            method = (getattr(req, "method", None) or "POST").upper()
            raw_url = str(getattr(req, "url", ""))
            try:
                parts = urlsplit(raw_url)
                host = parts.hostname or ""
                if ":" in host and not host.startswith("["):
                    host = f"[{host}]"
                if parts.port:
                    host = f"{host}:{parts.port}"
                safe_url = f"{parts.scheme}://{host}{parts.path}" if parts.scheme else parts.path
            except ValueError:
                safe_url = "<接口地址>"
            return f"{method} {safe_url or '<接口地址>'} → HTTP {status}"
        if status:
            return f"HTTP {status}"
        cur = getattr(cur, "__cause__", None)
    return None


def test_key(cfg) -> tuple:
    """用一份 LLMConfig 发一条最短请求，验证 base_url/model/api_key 能连通。

    cfg 即入参 —— 任意 OpenAI 兼容接口都能测，不再分 provider 写三个函数。
    返回 (bool, message)
    """
    try:
        from backend.services.llm_config import build_llm
        from langchain_core.messages import HumanMessage
        llm = build_llm(cfg.model_copy(update={"reasoning": False, "max_tokens": 1}))
        llm.invoke([HumanMessage(content="hi")])
        return True, "连接成功 ✓"
    except Exception as e:
        err_msg = str(e)
        low = err_msg.lower()
        if ("401" in err_msg or "unauthorized" in low
                or "invalid" in low or "authentication" in low
                or "api key" in low):
            return False, "密钥无效或余额不足，请检查后重试"
        ctx = _http_request_ctx(e)
        if ctx:
            # 不再把服务端那坨 HTML 原样吐给用户；改报「真正 POST 的 URL + 状态码」
            return False, (
                f"连接失败: {ctx}。请确认「接口地址」是该服务 OpenAI 兼容的 "
                f"API 根地址（形如 https://host/v1），程序会向该地址请求 "
                f"/chat/completions。"
            )
        if "connection error" in low or "connecterror" in low:
            return False, "无法连接模型服务。请检查接口地址、代理端口是否正常，以及 DNS / TLS 连接；这不一定是密钥错误。"
        return False, "连接失败。请检查接口地址、模型名和服务状态。"
