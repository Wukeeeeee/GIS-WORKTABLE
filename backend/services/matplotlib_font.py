"""
matplotlib 中文字体统一配置模块（公共模块）

提供跨模块的中文字体检测、fallback 和 rcParams 统一配置。
所有需要生成 matplotlib 图表的模块（tools.py、main.py、run_code 沙箱等）
应统一调用本模块的 setup_chinese_font()，避免重复实现字体配置。

用法：
    from backend.services.matplotlib_font import setup_chinese_font
    setup_chinese_font()

设计原则：
- 模块级只执行一次初始化（幂等）
- 按优先级检测系统真实存在的中文字体
- 提供多级 fallback（路径检测 -> fontManager 扫描 -> 英文兜底）
- 不影响英文、数字及其他 matplotlib 功能
- 不改变现有图表功能
"""

import os

# 初始化标记，确保只执行一次
_initialized = False


def _detect_chinese_font():
    """检测系统中可用的中文字体，返回 (font_name, font_path) 或 (None, None)。

    按优先级尝试：
    1. Windows: Microsoft YaHei -> SimHei -> Noto Sans SC -> SimSun -> KaiTi -> FangSong
    2. macOS: PingFang -> STHeiti -> Arial Unicode
    3. Linux: Noto Sans CJK -> WenQuanYi Zen Hei -> WenQuanYi Micro Hei
    """
    candidate_fonts = [
        # Windows（按优先级）
        (r"C:\Windows\Fonts\msyh.ttc", "Microsoft YaHei"),
        (r"C:\Windows\Fonts\msyhbd.ttc", "Microsoft YaHei Bold"),
        (r"C:\Windows\Fonts\simhei.ttf", "SimHei"),
        (r"C:\Windows\Fonts\NotoSansSC-VF.ttf", "Noto Sans SC"),
        (r"C:\Windows\Fonts\simsun.ttc", "SimSun"),
        (r"C:\Windows\Fonts\simkai.ttf", "KaiTi"),
        (r"C:\Windows\Fonts\simfang.ttf", "FangSong"),
        # macOS
        ("/System/Library/Fonts/PingFang.ttc", "PingFang SC"),
        ("/System/Library/Fonts/STHeiti Light.ttc", "STHeiti"),
        ("/Library/Fonts/Arial Unicode.ttf", "Arial Unicode MS"),
        # Linux
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK"),
        ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "WenQuanYi Zen Hei"),
        ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "WenQuanYi Micro Hei"),
    ]

    for fp, expected_name in candidate_fonts:
        if os.path.exists(fp):
            return expected_name, fp

    return None, None


def _fallback_scan_fontmanager():
    """兜底方案：遍历 fontManager 查找任何 CJK 字体。
    返回字体名称或 None。"""
    try:
        import matplotlib.font_manager as fm
        keywords = ["yahei", "simhei", "noto sans cjk", "noto sans sc",
                    "wqy", "pingfang", "heiti", "songti", "kaiti", "fangsong"]
        for f in fm.fontManager.ttflist:
            if any(kw in f.name.lower() for kw in keywords):
                return f.name
    except Exception:
        pass
    return None


def setup_chinese_font(force=False):
    """配置 matplotlib 中文字体。

    Args:
        force: 是否强制重新初始化（默认 False，模块级只执行一次）

    Returns:
        str: 配置的字体名称，或 None（未找到中文字体时）
    """
    global _initialized
    if _initialized and not force:
        return None

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm

        font_name = None

        # 第一级：路径检测
        detected_name, font_path = _detect_chinese_font()
        if font_path and os.path.exists(font_path):
            try:
                fm.fontManager.addfont(font_path)
                prop = fm.FontProperties(fname=font_path)
                font_name = prop.get_name()
            except Exception:
                font_name = detected_name  # 使用预期名称

        # 第二级：fontManager 兜底扫描
        if not font_name:
            font_name = _fallback_scan_fontmanager()

        # 配置 rcParams
        if font_name:
            current_sans = plt.rcParams.get("font.sans-serif", ["DejaVu Sans"])
            # 确保中文字体在最前面，同时保留原有 fallback 链
            if font_name not in current_sans:
                plt.rcParams["font.sans-serif"] = [font_name] + list(current_sans)
            else:
                # 已存在则移到最前
                sans_list = [n for n in current_sans if n != font_name]
                plt.rcParams["font.sans-serif"] = [font_name] + sans_list
            plt.rcParams["font.family"] = "sans-serif"
            plt.rcParams["axes.unicode_minus"] = False
            print(f"[matplotlib_font] 中文字体已配置: {font_name}")
        else:
            print("[matplotlib_font] 警告: 未找到中文字体，图表中文可能显示为方块")

        # 统一设置 ggplot 风格（与原 run_code 沙箱保持一致）
        try:
            plt.style.use("ggplot")
        except Exception:
            pass

        _initialized = True
        return font_name

    except Exception as e:
        print(f"[matplotlib_font] 字体初始化异常: {e}")
        return None


def get_sandbox_setup_code() -> str:
    """返回可注入到 run_code 沙箱的 matplotlib 中文字体配置代码。

    由于 run_code 在独立子进程中执行用户代码，无法直接 import 本模块，
    因此通过此函数生成自包含的字体配置代码字符串，注入到 _setup_blocks 中。
    字体列表和 fallback 逻辑与 setup_chinese_font() 保持一致。

    Returns:
        str: 可执行的 Python 代码字符串
    """
    return r'''
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as _fm
import os as _os

# 候选字体路径（按优先级，与公共模块保持一致）
_candidate_fonts = [
    r'C:\Windows\Fonts\msyh.ttc',
    r'C:\Windows\Fonts\msyhbd.ttc',
    r'C:\Windows\Fonts\simhei.ttf',
    r'C:\Windows\Fonts\NotoSansSC-VF.ttf',
    r'C:\Windows\Fonts\simsun.ttc',
    r'C:\Windows\Fonts\simkai.ttf',
    r'C:\Windows\Fonts\simfang.ttf',
    '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/STHeiti Light.ttc',
    '/Library/Fonts/Arial Unicode.ttf',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
]

_font_set = False
for _fp in _candidate_fonts:
    if _os.path.exists(_fp):
        try:
            _fm.fontManager.addfont(_fp)
            _prop = _fm.FontProperties(fname=_fp)
            _font_name = _prop.get_name()
            plt.rcParams['font.sans-serif'] = [_font_name] + plt.rcParams.get('font.sans-serif', ['DejaVu Sans'])
            plt.rcParams['font.family'] = 'sans-serif'
            plt.rcParams['axes.unicode_minus'] = False
            _font_set = True
            break
        except Exception:
            continue

# 兜底：遍历 fontManager 查找任何 CJK 字体
if not _font_set:
    try:
        for _f in _fm.fontManager.ttflist:
            if any(_kw in _f.name.lower() for _kw in ['yahei', 'simhei', 'noto sans cjk', 'noto sans sc', 'wqy', 'pingfang', 'heiti', 'songti', 'kaiti', 'fangsong']):
                plt.rcParams['font.sans-serif'] = [_f.name] + plt.rcParams.get('font.sans-serif', ['DejaVu Sans'])
                plt.rcParams['font.family'] = 'sans-serif'
                plt.rcParams['axes.unicode_minus'] = False
                _font_set = True
                break
    except Exception:
        pass

plt.style.use("ggplot")
'''


# 模块加载时自动执行一次（供直接 import 时使用）
setup_chinese_font()
