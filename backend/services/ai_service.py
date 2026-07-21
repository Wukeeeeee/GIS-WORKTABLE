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

from openai import OpenAI
import os, time, tempfile, json, datetime, re, subprocess

# ---- 临时输出目录 ----
_TEMP_OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "gis_worktable_output")
os.makedirs(_TEMP_OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.join(_TEMP_OUTPUT_DIR, "output"), exist_ok=True)

# Browser-Use / LLM 工具需要用到的当前会话 API Key
_current_api_key = ""
_current_provider = "deepseek"

# 技能目录（ Markdown 文件，由 GLM 路由加载）
_SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "skills")

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
    """检测新消息与最近对话历史的话题相关性（字符级 bigram Jaccard 相似度）"""
    recent_user_msgs = []
    for msg in reversed(history):
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role == "user":
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
            if isinstance(content, str):
                recent_user_msgs.append(content)
            if len(recent_user_msgs) >= 3:
                break

    if not recent_user_msgs:
        return True

    def _char_bigram_set(text: str) -> set:
        cleaned = re.sub(r'[^一-鿿\w]', '', text)
        if len(cleaned) <= 1:
            return set(cleaned)
        return {cleaned[i:i+2] for i in range(len(cleaned) - 1)}

    new_bigrams = _char_bigram_set(new_message)
    if not new_bigrams:
        return True

    max_similarity = 0.0
    for old_msg in recent_user_msgs:
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

只返回 JSON 数组格式，例如：["geometry", "visualization"]
不要有任何其他文字。如果不需要任何技能，返回 []"""


def _glm_route_skills(message: str, glm_api_key: str = None) -> list:
    """GLM 路由：分析用户消息，返回需要的技能标签列表"""
    try:
        client = OpenAI(
            api_key=glm_api_key or _get_default_glm_key(),
            base_url="https://open.bigmodel.cn/api/paas/v4/"
        )
        resp = client.chat.completions.create(
            model="glm-4.7-flash",
            messages=[
                {"role": "system", "content": _GLM_ROUTER_PROMPT},
                {"role": "user", "content": message}
            ],
            temperature=0.1,
            max_tokens=200,
        )
        text = resp.choices[0].message.content.strip()
        skills = json.loads(text)
        if isinstance(skills, list):
            return skills
        return []
    except Exception as e:
        print(f"[GIS] GLM 路由分析失败（不影响主流程）: {e}", flush=True)
        return []


def _agnes_route_skills(message: str, agnes_api_key: str = None) -> list:
    """Agnes 自路由：用 Agnes 自己分析消息，返回需要的技能标签列表"""
    try:
        client = OpenAI(
            api_key=agnes_api_key or "",
            base_url="https://apihub.agnes-ai.com/v1",
            timeout=15,
        )
        resp = client.chat.completions.create(
            model="agnes-2.0-flash",
            messages=[
                {"role": "system", "content": _GLM_ROUTER_PROMPT},
                {"role": "user", "content": message}
            ],
            temperature=0.1,
            max_tokens=200,
        )
        text = resp.choices[0].message.content.strip()
        skills = json.loads(text)
        if isinstance(skills, list):
            return skills
        return []
    except Exception as e:
        print(f"[GIS] Agnes 自路由失败（不影响主流程）: {e}", flush=True)
        return []


def _load_skill_from_file(skill_name: str) -> str:
    """从 skills/ 目录加载技能 Markdown 文件"""
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

SYSTEM_PROMPT = """你是一个GIS WorkTable内置AI助手（多模型协作）

 ## 你的能力
  - 回答地理信息、地图、空间分析相关的问题
  - 帮助用户理解 GIS 数据和处理流程
  - 提供 GIS 数据处理方法和示例代码
  - 提供与地理有关系的任何数据（人口、经济、环境等）
  - 提供与地理相关的任何知识
  - 提供与地理相关的任何工具(GIS、遥感、地理统计等)

 ## 回复风格
  - 以中文为主，必要时使用英文术语
  - 简洁直白，不要使用表情符号
  - 可以使用 Markdown 格式组织内容（标题 `##`、列表 `-`、代码块 ```、加粗 `**` 等），让回复结构清晰
  - 列出多项内容时，每项单独一行，同类数据放一起
  - 涉及操作步骤时，分点列出，清晰易懂
  - 如果是简单问题，直接回答即可，无须反问
  - 问题不清晰时，主动询问用户补充信息

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

 ## 工具使用优先级（必须遵守）
  - **优先用专用工具**：amap_geocode / amap_poi_search / datav_boundary / network_analysis / download_road_network / unified_aoi_search / unified_aoi_extract / create_heatmap / create_chart / field_calculate / measure_area / layer_control
  - **execute_python 是最后选择**，仅当前述专用工具都不满足需求时才使用。大多数 GIS 需求都有专用工具，不需要用 execute_python 写代码。
  - 使用 execute_python 时**禁止硬编码 API Key**（高德 Key 已自动注入为 _AMAP_KEY 变量，直接从变量读取）。
  - 如果不确定用哪个工具，优先选专用工具而非 execute_python——专用工具有更好的错误处理和坐标转换。

  每个工具的具体使用规则（参数、约束、最佳实践）见各工具的 description，不必事先记忆。

 ## 国外地点
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

## 工具使用优先级
 - 优先使用专用工具（amap_geocode / amap_poi_search / datav_boundary / network_analysis 等），execute_python 是最后选择
 - 有专用工具的操作不得用 execute_python 代替
 - execute_python 中禁止硬编码 API Key

每个工具的具体使用规则（参数、约束、最佳实践）见各工具的 description，不必事先记忆。

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
# API 密钥管理
# ============================================================

API_KEY_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "apikey.txt")
GLM_API_KEY_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "glm_apikey.txt")


def _get_default_key() -> str:
    try:
        with open(API_KEY_FILE, 'r') as f:
            return f.read().strip()
    except:
        return ""


def _get_default_glm_key() -> str:
    try:
        with open(GLM_API_KEY_FILE, 'r') as f:
            return f.read().strip()
    except:
        return ""


def _build_client(api_key: str = None, provider: str = "deepseek") -> OpenAI:
    if provider in ("glm", "glm-routed"):
        key = api_key or _get_default_glm_key()
        return OpenAI(api_key=key, base_url="https://open.bigmodel.cn/api/paas/v4/")
    elif provider == "agnes":
        key = api_key or ""
        return OpenAI(api_key=key, base_url="https://apihub.agnes-ai.com/v1", timeout=30)
    else:
        key = api_key or _get_default_key()
        return OpenAI(api_key=key, base_url="https://api.deepseek.com")


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


def _build_system_content(provider: str, message: str, force_skills: list = None) -> tuple:
    """构建 system prompt，返回 (system_content, skill_text, model_display)

    KV 缓存友好设计：
    - SYSTEM_PROMPT / SYSTEM_PROMPT_GLM 是固定前缀（永远不变）
    - 所有可变部分（时间、模型名、技能）统一追加到末尾
    - 这样 API 服务端可以命中前缀 KV 缓存，首 token 时间从 10-30s 降到 0.5-1s
    """
    is_routed = (provider in ("deepseek-routed", "glm-routed", "agnes"))
    model_display = {"deepseek-routed": "DeepSeek V4 Flash+", "glm-routed": "GLM-4.7-Flash+", "agnes": "Agnes 2.0 Flash+"}.get(provider, "DeepSeek V4 Flash+")
    now = datetime.datetime.now().astimezone()

    # 固定前缀（永远不变 → KV cache 命中）
    if provider in ("glm", "glm-routed"):
        system_content = SYSTEM_PROMPT_GLM
    else:
        system_content = SYSTEM_PROMPT

    # === 可变后缀（每次追加在末尾，不影响前缀缓存） ===
    appendix_parts = []

    # 当前模型名
    appendix_parts.append(f"当前运行模型：{model_display}")

    # 当前时间
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    tz_str = now.tzname() or 'UTC'
    appendix_parts.append(f"当前时间：{now_str} ({tz_str})")
    appendix_parts.append("注意：根据当前时间判断数据的时效性")

    # 路由（统一用 GLM 路由 — 国内延迟低，避免自路由的跨洋往返）
    all_skills = []
    if is_routed:
        glm_key = _get_default_glm_key()
        if glm_key:
            routed_skills = _glm_route_skills(message, glm_key)
        else:
            routed_skills = []
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
                _layer_lines.append(f"  - {_lyr['name']}：{_cnt} 个 {_typ}{_ext}")
            appendix_parts.append("## 当前已加载的图层\n" + "\n".join(_layer_lines) +
                "\n重要：如果已有路网图层，优先使用现有图层做分析，严禁重复下载。")
    except Exception:
        pass

    # 用分隔线连接可变部分（清晰的分界，不影响前缀缓存）
    if appendix_parts:
        system_content += "\n\n---\n" + "\n\n".join(appendix_parts)

    return system_content, skill_text, model_display


def _build_langgraph_messages(system_content: str, history: list) -> list:
    """将 system_content + 历史记录转为 LangChain BaseMessage 列表"""
    from langchain_core.messages import SystemMessage, HumanMessage
    messages = [SystemMessage(content=system_content)]
    for msg in history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            messages.append(SystemMessage(content=content or ""))
        elif role == "user":
            messages.append(HumanMessage(content=content or ""))
    return messages


# ============================================================
# 主入口: chat_with_ai（重构后使用 LangGraph Agent）
# ============================================================

def chat_with_ai(message: str, session_id: str = "default", api_key: str = None,
                 provider: str = "deepseek", force_skills: list = None,
                 amap_key: str = None) -> dict:
    """
    调用 AI 进行对话（使用 LangGraph Agent）

    原来：手写 while/if 循环管理工具调用（15+ elif 分支）
    现在：LangGraph StateGraph 自动管理工具调用流程

    返回 dict:
        {
            "response": str,           # AI 回复文本
            "layers": [...],           # 待加载图层列表
            "images": [...],           # 生成的图表
            "heatmap": {...} | None,   # 热力图数据
            "clear_layers": bool,      # 是否清空地图
            "pending_suggestions": {...} | None,  # AOI 候选
        }
    """
    global _current_api_key, _current_provider
    _current_api_key = api_key or _get_default_key()
    _current_provider = provider

    # 自动清理过期缓存
    clean_old_cache(7)

    # 获取或创建历史记录
    history = _get_or_create_history(session_id, message)

    system_content, skill_text, model_display = _build_system_content(provider, message, force_skills)

    # 构建消息列表（LangGraph 用 BaseMessage 格式）
    from langchain_core.messages import SystemMessage, HumanMessage

    langgraph_messages = [SystemMessage(content=system_content)]

    # 将历史记录转为 LangChain 消息格式
    for msg in history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            langgraph_messages.append(SystemMessage(content=content or ""))
        elif role == "user":
            langgraph_messages.append(HumanMessage(content=content or ""))

    # === 调用 LangGraph Agent ===
    from backend.services.graph import run_agent

    start_time = time.time()
    print(f"[GIS] [{model_display}] 启动 LangGraph Agent...", flush=True)

    result = run_agent(
        messages=langgraph_messages,
        api_key=api_key or _get_default_key(),
        provider=provider,
        amap_key=amap_key or "",
        skill_text=skill_text,
        original_message=message,
    )

    elapsed = time.time() - start_time
    print(f"[GIS] [{model_display}] LangGraph Agent 完成，耗时 {elapsed:.1f}s", flush=True)

    ai_reply = result.get("response", "")

    # 记录本轮工具调用过程到历史（简化：只记录用户消息和 AI 回复）
    # 注意：LangGraph 自动管理工具调用过程，不需要把 tool 消息存到 history
    history.append({"role": "assistant", "content": ai_reply})

    # 限制历史长度
    if len(history) > _MAX_HISTORY:
        conversation_history[session_id] = history[-_MAX_HISTORY:]
        history = conversation_history[session_id]

    _save_history(session_id, history)

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
            provider=provider,
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
    # 清除注册的图层
    try:
        from backend.services.tools import _registered_layers, _pending_layers, _pending_images
        _registered_layers.clear()
        _pending_layers.clear()
        _pending_images.clear()
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
    return "已发送取消信号"


# ============================================================
# 测试 API 密钥
# ============================================================

def test_deepseek_key(api_key: str) -> tuple:
    try:
        client = _build_client(api_key)
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1
        )
        return True, "连接成功 ✓"
    except Exception as e:
        err_msg = str(e)
        if "401" in err_msg or "unauthorized" in err_msg.lower() or "invalid" in err_msg.lower():
            return False, "密钥无效或余额不足，请检查后重试"
        return False, f"连接失败: {err_msg}"


def test_agnes_key(api_key: str) -> tuple:
    try:
        client = OpenAI(api_key=api_key, base_url="https://apihub.agnes-ai.com/v1")
        response = client.chat.completions.create(
            model="agnes-2.0-flash",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1
        )
        return True, "连接成功 ✓"
    except Exception as e:
        err_msg = str(e)
        if "401" in err_msg or "unauthorized" in err_msg.lower() or "invalid" in err_msg.lower():
            return False, "密钥无效或余额不足，请检查后重试"
        return False, f"连接失败: {err_msg}"


def test_glm_key(api_key: str) -> tuple:
    try:
        client = _build_client(api_key, provider="glm")
        response = client.chat.completions.create(
            model="glm-4.7-flash",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1
        )
        return True, "连接成功 ✓"
    except Exception as e:
        err_msg = str(e)
        if "401" in err_msg or "unauthorized" in err_msg.lower() or "invalid" in err_msg.lower():
            return False, "密钥无效或余额不足，请检查后重试"
        return False, f"连接失败: {err_msg}"


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
