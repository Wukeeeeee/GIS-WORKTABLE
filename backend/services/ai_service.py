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

import os, time, tempfile, json, datetime, re, subprocess
from typing import Optional

# ---- 临时输出目录 ----
_TEMP_OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "gis_worktable_output")
os.makedirs(_TEMP_OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.join(_TEMP_OUTPUT_DIR, "output"), exist_ok=True)

# Browser-Use / LLM 工具需要用到的当前会话 API Key
_current_api_key = ""
_current_provider = "deepseek"

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
    "matplotlib": "Matplotlib 数据可视化，支持线图/散点图/柱状图/直方图/热图/六边形分箱/3D图。中文字体已配。plt.savefig('output/chart_name.png')",
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

_GLM_ROUTER_PROMPT = """你是一个技能路由分析器。分析用户的请求，判断需要调用哪些技能文件来辅助完成任务。
可选技能文件标签（只从以下列表中选择，不需要就返回空列表）：

- geometry：几何操作（缓冲区、空间相交、合并、差异、质心、简化、修复无效几何）
- aoi：AOI 建筑轮廓提取（百度地图）
- datav：行政区划边界（省/市/区三级）
- heatmap：热力图生成（基于已有点图层）
- visualization：数据可视化（matplotlib 统计图表、pyecharts 交互图表）
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
    ① **严禁自称“无法直接生成PNG/PDF图片”**：平台完全支持通过 `execute_python`（matplotlib）生成高分辨率 PNG 专题图并保存至 `output/` 目录（前端会自动识别并渲染展示可下载图片），或通过 `create_chart` 生成图表。**严禁对用户声称“我不能直接生成图片文件”或“没有图形渲染能力”！**
    ② **严禁输出纯文本 XML/SVG 代码让用户手动保存**：严禁把 `<svg>...</svg>` 代码直接扔在正文中让用户“存成 .svg 双击看”！需要图件必须调用工具真实生成图片或图表。
    ③ **严禁向用户索要本地 SHP/GeoJSON 文件路径**：中国各级行政区划边界系统内置了完整的 DataV 矢量数据源（调用 `datav_boundary` 即可一键获取真实边界并在交互地图上展示）。严禁声称“我不给你画假轮廓，你手上有shp给我路径”这类卸责推脱话术！
    ④ **双轨成果交付**：制作专题图时，必须同时：1) 调用 `datav_boundary` 获取真实边界并在交互地图展示；2) 调用 `execute_python` (matplotlib) 绘制带地理轮廓和指标卡片的专业专题图保存至 `output/` 目录（或调用 `create_chart` 生成统计图表），直接交付成果。

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
  - **优先用专用工具**：amap_geocode / amap_poi_search / datav_boundary / network_analysis / download_road_network / cn_aoi_search / cn_aoi_extract / create_heatmap / create_chart / field_calculate / measure_area / layer_control
  - **地理编码/坐标查询必须调用 amap_geocode 工具**：用户询问"XX在哪""XX的坐标""XX经纬度""定位XX"等问题时，必须先调用 amap_geocode 获取真实坐标，禁止凭模型记忆直接返回坐标数值。反向地理编码用 reverse_geocode，批量用 batch_geocode。
  - **国内建筑/场所/AOI轮廓必须用 cn_aoi_search + cn_aoi_extract（百度地图）**：用户要求提取建筑、商场、学校、机场、公园等场所轮廓时，必须先调用 cn_aoi_search 搜索候选，等用户选择后再用 cn_aoi_extract 提取边界。百度提取失败时如实告诉用户"暂时无法获取该地点轮廓"，**禁止**用 osmnx/OSM 或其他方式自行估算、绘制近似边界。osmnx 仅用于路网下载和国外行政边界。
  - **国内行政区划边界必须用 datav_boundary**：用户要求获取省/市/区/县行政边界时，必须调用 datav_boundary 工具。如果 datav_boundary 返回空或失败，如实告诉用户"暂时无法获取该行政区划边界"，**禁止**用 osmnx/OSM 或 execute_python 自行估算、绘制近似边界。
  - **execute_python 使用边界与严禁甩代码原则**：
    ① 对已有专用工具的操作（地理编码、行政边界、缓冲区、网络分析等），禁止用 execute_python 代替。
    ② **但当需要生成自定义专题图、指标看板、复杂多子图图表（matplotlib/pyecharts）时，你必须自己调用 execute_python 直接执行代码生成成果图**！
    ③ **绝对严禁在正文中输出 Python 代码并让用户去本地或 Jupyter 运行**！严禁说“我没法在这边直接出图，你复制到本地运行”！平台已预装 Python 沙箱与绘图库，必须由你直接调用工具执行，将图片保存到 output 目录由系统自动展示给用户。
  - 使用 execute_python 时**禁止硬编码 API Key**（高德 Key 已自动注入为 _AMAP_KEY 变量，直接从变量读取）。
  - **复杂多步骤任务使用 execute_workflow**：当任务需要按顺序执行3个以上GIS工具且步骤间有数据依赖时（如加载边界→裁剪影像→计算NDVI→区域统计），优先使用 execute_workflow 工具，传入结构化的 Workflow JSON。这样可以清晰展示分析流程、自动传递上游输出、失败时停止后续步骤。简单任务或无依赖的并行任务不需要用 Workflow，直接调工具即可。
  - 如果不确定用哪个工具，优先选专用工具而非 execute_python——专用工具有更好的错误处理和坐标转换。
  - **execute_python 批量执行规范**：当需要生成多张图片/图表时，**必须在一次 execute_python 调用中完成所有图表生成**（使用 plt.subplot 或多次 plt.savefig），不要为每张图片单独调用 execute_python。单独调用会触发过热保护（上限20次/请求）。
  - **图表/地图制图规范（强制执行）**：使用 matplotlib 生成任何图表或地图成果图时：
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
      - **原生备选方案（指引线错落）**：若不使用 adjustText，对密集区域必须使用 `ax.annotate(..., xy=(lon, lat), xytext=(...), arrowprops=dict(arrowstyle='-', color='#888', lw=0.5))` 将注记引向东北/东南/西北不同方位拉开间距。
      - 遥感分类/土地利用图必须在图例中标注类别名称与颜色对应关系。
  - **专题图与空间可视化规范（强制执行，区分单区与多区）**：
    ① **单区域专题图（单个行政区/城市，如"鼓楼区"、"南京市"，仅有单个面要素）**：
      - 单个面要素无法进行多级分级设色（数值无差异）。
      - **默认直接交付，严禁追问用户**：
        a. 调用 datav_boundary 加载该行政区矢量边界到地图（如 datav_boundary("南京市鼓楼区")）；
        b. 结合已有统计数据，生成单区经济/人口指标面板、结构图表（调用 create_chart 生成产业结构/指标图表，或使用 execute_python 绘制行政区轮廓+关键指标信息图）；
        c. 直接交付成果，**严禁要求用户在"对比多地"与"单区结构"之间二选一**，**严禁询问底图格式（默认内置边界）或图型**。
    ② **多区域专题图（一个上级行政区包含多个子要素，如"全国各省"、"南京市各区"，要素数 >= 2）**：
      - 将包含指标字段的矢量面边界加载为地图图层（如 datav_boundary("南京市", sub_district=1)），并调用 `spatial_graduated_colors` 工具应用分级色彩渲染（让用户在交互地图上直观看到分级设色）。
      - 若同时生成统计图件，确保地图图层与图件双轨呈现。
    ③ **底图数据与参数默认值**：
      - 底图默认且必须使用内置行政区划数据（datav_boundary），**严禁询问用户是否有 SHP / GeoJSON**；
      - 符号化与色带默认采用最佳制图规范（经济指标默认 blues/reds/oranges），**严禁向用户询问图型选择（分级/气泡/柱状等）**。
  - **天气数据用 fetch_weather_data**：用户询问天气、降水、温度、风速等气象数据时，先用 amap_geocode 获取坐标，再调用 fetch_weather_data（Open-Meteo，免费无 Key）。不要用 execute_python 自写请求。
  - **地震数据用 fetch_earthquake_data**：用户询问地震分布、震中、近期地震时，调用 fetch_earthquake_data（USGS，免费无 Key），数据会自动加载到地图，可继续做热点/缓冲区分析。

  每个工具的具体使用规则（参数、约束、最佳实践）见各工具的 description，不必事先记忆。

 ## 多轮上下文继承与零追问默认执行准则（核心原则，必须遵守）
 当用户在多轮对话中提出简短或后续需求（如"需要专题图"、"做成图"、"在地图上展示"、"分析一下"、"导出"等）：
 1. **严格继承前序实体与属性（上下文复用）**：
    - 必须直接复用上一轮已确认或已讨论的**地理实体**（如南京市鼓楼区）、**统计年份**（如2025年）、**经济/统计指标**（如GDP、三产结构）及**具体数值**。
    - 调用工具时必须传入完整的已确认行政区全称（例如调用 `datav_boundary("南京市鼓楼区")`），严禁退化为模糊泛指名称（如"鼓楼区"）。
 2. **行动优先，默认执行（杜绝连珠炮式盘问）**：
    - 用户的核心诉求是"看到成果"，而不是"填问卷"。凡是有合理默认值的参数（底图来源默认内置、制图形式默认匹配单区/多区最优方案、色带默认专业配色），**必须直接执行并交付**。
    - 严禁因为图型、底图格式未指定就一律要求用户确认！
    - 只有当缺少真正关键且无法推断的信息时，才允许追问。若需要询问，一次最多问一个最关键问题（调用 ask_user_choice 按钮），**严禁抛出问卷式长篇大论，更严禁要求用户输入固定格式指令（如“回复 方案A + 气泡 + 内置边界”）**。
 3. **严禁自我加戏与擅自扩大范围**：
    - 用户未主动要求时，**严禁将单个行政区的问题膨胀为多个同名行政区对比或跨区域横向对比**（例如用户问鼓楼区GDP后要专题图，严禁主动把福州、徐州、开封鼓楼区拉来做对比，严禁强推跨区域对比方案）。

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
  - 算面积/距离前：检查 CRS，WGS84 经纬度必须先投影（measure_area/measure_distance 已自动处理，自定义代码需注意）
  - 缓冲区分析：经纬度下做缓冲会变形，unit=m 时工具内部自动投影
  - 空间连接：predicate 默认用 intersects，严格包含用 within，找相邻用 touches
  - 叠置分析：求共同区域用 intersect，合并用 union，去掉部分用 difference，截取用 clip
  - 插值：点密集用 IDW，需要平滑用 RBF，需要误差估计用克里金（execute_python）
  - 分类：有训练样本用 RandomForest，无样本用 KMeans，单指数提取用阈值分割
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
  - 国外边界用 execute_python 调 osmnx（Overpass 镜像）获取
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
  - 优先使用专用工具（amap_geocode / amap_poi_search / datav_boundary / network_analysis 等），execute_python 是最后选择
  - 有专用工具的操作不得用 execute_python 代替
  - execute_python 中禁止硬编码 API Key
  - **execute_python 批量执行规范**：当需要生成多张图片/图表时，**必须在一次 execute_python 调用中完成所有图表生成**（使用 plt.subplot 或多次 plt.savefig），不要为每张图片单独调用 execute_python。单独调用会触发过热保护（上限20次/请求）。
  - **图表/地图制图规范（强制执行）**：使用 matplotlib 生成任何图表或地图时：①标题明确规范（无多余废话）；②必须带标准图例或色条（注明指标与单位），遥感分类图必须标明类别对应颜色；③**注记严禁相互堆叠重叠**：长三角、珠三角等密集区域必须使用 `adjustText`（已预装：`from adjustText import adjust_text; adjust_text(texts, arrowprops=dict(arrowstyle='->', color='#666', lw=0.6))`）或引出线避让，文字简练（如“上海\n4.7万亿”），边框浅灰细线，严禁挤成黑块；④保存必须用 `bbox_inches='tight', dpi=150`。生成后在回复中说明主要图例与结论。

  - **专题图制作与空间可视化规范（强制执行）**：
    ① 单行政区专题图（如“鼓楼区”、“南京市”）：单个面要素无法分级设色，默认调用 datav_boundary 加载边界，结合统计数据生成单区指标看板/信息图（create_chart/execute_python），直接交付，严禁追问用户选择图型、底图或强推多区对比。
    ② 多行政区专题图（如“全国各省”、“南京各区”，要素数>=2）：调用 datav_boundary 加载子行政区，结合指标字段调用 spatial_graduated_colors 分级色彩渲染。
    ③ 底图默认内置 datav_boundary，严禁询问用户是否有 SHP / GeoJSON。

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
_HISTORY_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "cache", "history")


def _ensure_history_dir():
    os.makedirs(_HISTORY_DIR, exist_ok=True)


def _history_path(session_id: str) -> str:
    return os.path.join(_HISTORY_DIR, f"session_{session_id}.json")


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


def commit_assistant_reply(session_id: str, response: str, reasoning: str = None):
    """把一轮 AI 回复写回会话历史并落盘（幂等：末条已是 assistant 则跳过）。

    普通 /api/chat 与 SSE /api/chat/stream 共用，保证两种入口的对话历史一致：
    stream 之前只 append 用户消息、从不写回 AI 回复，导致下一轮模型看不到
    上一轮 AI 说了什么（“回复继续即可加载”这类状态随之丢失）。
    """
    if not response or not response.strip():
        return
    history = conversation_history.get(session_id)
    if history is None:
        history = _load_history(session_id)
        conversation_history[session_id] = history
    if history and history[-1].get("role") == "assistant":
        return  # 已提交过，防重复
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

    cache_root = os.path.dirname(_CACHE_DIR)
    if os.path.isdir(cache_root):
        for fname in os.listdir(cache_root):
            if not (fname.endswith('.json') and len(fname) == 44):
                continue
            fpath = os.path.join(cache_root, fname)
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
    if session_id not in conversation_history:
        conversation_history[session_id] = _load_history(session_id)
    history = conversation_history[session_id]
    # 话题切换检测
    if history:
        topic_related = _check_topic_relevance(message, history)
        if not topic_related:
            history.clear()
    # 加入用户消息
    history.append({"role": "user", "content": message})
    return history


def _build_system_content(cfg, message: str, session_id: str = "default", force_skills: list = None) -> tuple:
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
                _lyr_name = _lyr.get('filename') or _lyr.get('name', '未知')
                _layer_lines.append(f"  - {_lyr_name}：{_cnt} 个 {_typ}{_ext}{_fields_str}")
            appendix_parts.append("## 当前已加载的图层\n" + "\n".join(_layer_lines) +
                "\n重要：如果已有路网图层，优先使用现有图层做分析，严禁重复下载。")
    except Exception:
        pass

    # === Task Manager: 注入任务工作上下文（最新代码 + Artifact + 执行历史） ===
    try:
        from backend.services.tools import get_current_task_id
        _tid = get_current_task_id()
        if _tid:
            from backend.services.task_manager import build_task_context
            _task_ctx = build_task_context(_tid)
            if _task_ctx:
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
    if action and action.get("action") == "choose_option":
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

    cmd = pending_action.classify_short_command(message)
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
    _get_or_create_history(session_id, message)
    commit_assistant_reply(session_id, result.get("response", ""), None)
    pending_action.clear_pending_action(session_id)
    return result


# ============================================================
# 主入口: chat_with_ai（重构后使用 LangGraph Agent）
# ============================================================

def chat_with_ai(message: str, session_id: str = "default", cfg=None,
                 force_skills: list = None, amap_key: str = None,
                 provider: str = "", mode: str = "full") -> dict:
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
    global _current_api_key, _current_provider
    if cfg is None:
        raise ValueError("chat_with_ai 需要 LLMConfig（cfg），请先 resolve_llm_config()")
    _current_api_key = cfg.api_key
    _current_provider = provider or cfg.model

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

    system_content, skill_text, model_display = _build_system_content(cfg, message, session_id, force_skills)

    # 构建消息列表（LangGraph 用 BaseMessage 格式，assistant + reasoning 一并带回）
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
    )

    elapsed = time.time() - start_time
    print(f"[GIS] [{model_display}] LangGraph Agent 完成，耗时 {elapsed:.1f}s", flush=True)

    # 写回本轮 AI 回复到历史并落盘（与 SSE 流共用同一函数）
    ai_reply = result.get("response", "")
    commit_assistant_reply(session_id, ai_reply, result.get("reasoning"))

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
# 会话状态导出（供工程持久化使用）
# ============================================================

def get_session_state(session_id: str = "default") -> dict:
    """返回当前会话的快照：消息、图层、provider"""
    from backend.services.tools import get_registered_layers_snapshot
    history = conversation_history.get(session_id, [])
    return {
        "messages": history,
        "layers": get_registered_layers_snapshot(),
    }


# ============================================================
# 清除记忆
# ============================================================

def clear_memory(session_id: str = "default"):
    """清除指定会话的记忆"""
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
            _pending_layer_ops, reset_state, get_current_task_id,
        )
        # 先删除 task_manager 中的当前任务（磁盘文件 + 内存），避免旧任务上下文残留
        try:
            _tid = get_current_task_id()
            if _tid:
                from backend.services.task_manager import delete_task
                delete_task(_tid)
        except Exception:
            pass
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


# ============================================================
# 取消 AI 请求
# ============================================================

_request_cancelled = False

def request_cancel():
    """标记取消当前 AI 请求（由 /api/cancel 端点调用）"""
    global _request_cancelled
    _request_cancelled = True
    print("[GIS] 用户请求取消，已设置 _request_cancelled = True", flush=True)
    return "已发送取消信号"


# ============================================================
# 测试 LLM 连接（通用 /api/test-key）
# ============================================================

def _http_request_ctx(e: Exception) -> Optional[str]:
    """从 SDK 抛出的 HTTP 异常链里取出「实际发出的请求」上下文。

    只读异常对象上的 request.method / request.url / status_code，不碰
    header/body，绝不包含 API Key。作用：把 405/404 这类「到底 POST 到了哪个
    URL、服务器回了什么状态码」暴露给用户，方便核对「接口地址」填得对不对。
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
            url = str(getattr(req, "url", ""))
            return f"{method} {url} → HTTP {status}"
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
        return False, f"连接失败: {err_msg[:200]}"


# ============================================================
# Browser-Use 浏览器操控（保留原实现，不迁移为工具）
# ============================================================

def browser_operate(task: str, url: str = "") -> str:
    """使用 Browser-Use AI Agent 操控浏览器执行复杂任务"""
    import asyncio, sys
    from backend.services.ai_service import _current_api_key, _current_provider

    if not _current_api_key:
        return "错误：未配置 API Key，browser_operate 需要 API Key 驱动 AI 决策"

    script = r'''
import asyncio, sys, os
os.environ["ANONYMIZED_TELEMETRY"] = "false"
from browser_use import Agent
from langchain_openai import ChatOpenAI
async def main():
    api_key = os.environ.get("_BROWSER_API_KEY", "")
    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=api_key,
        base_url="https://api.deepseek.com",
        temperature=0,
    )
    llm.provider = "openai"
    agent = Agent(task=sys.argv[1], llm=llm, use_vision=False, max_actions_per_step=5)
    result = await agent.run(max_steps=20)
    text = str(result)
    if len(text) > 5000:
        text = text[:5000] + "\n\n...(结果过长已截断)"
    return text
if __name__ == "__main__":
    try:
        print(asyncio.run(main()))
    except Exception as e:
        print(f"Browser-Use 执行错误: {str(e)}")
'''

    try:
        result = subprocess.run(
            [sys.executable, '-c', script, task],
            capture_output=True, timeout=120,
            env={**os.environ.copy(), 'PYTHONIOENCODING': 'utf-8', '_BROWSER_API_KEY': _current_api_key},
        )
        stdout = result.stdout.decode('utf-8', errors='replace')
        stderr = result.stderr.decode('utf-8', errors='replace')
        if result.returncode != 0:
            return f"Browser-Use 执行失败：{stderr[:500]}"
        return stdout.strip() or f"Browser-Use 未返回结果（stderr: {stderr[:200] or '无'}）"
    except subprocess.TimeoutExpired:
        return "错误：Browser-Use 执行超时（120 秒）"
    except Exception as e:
        return f"Browser-Use 错误：[{type(e).__name__}] {str(e)[:300]}"
