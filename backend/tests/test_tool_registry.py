# -*- coding: utf-8 -*-
"""工具注册完整性守卫

tools.py 里的工具靠一个手写的 `tools` 列表注册给 LLM。忘写一行 = 这个工具
对模型完全不可见，而且不会有任何报错——只是"AI 突然不会干某件事了"。

这里把静态结构约束钉成测试：新增工具忘注册、重复注册、缺 docstring，
都会在 CI/本地测试阶段暴露，而不是等到线上才发现 AI 不会用某个功能。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from backend.services import tools as T
from backend.services.tools import tools as TOOL_LIST


def _defined_tools():
    """模块中所有 @tool 装饰出来的对象：{name: obj}"""
    from langchain_core.tools import BaseTool
    return {obj.name: obj for obj in vars(T).values() if isinstance(obj, BaseTool)}


def test_tools_module_imports_and_has_substantial_tools():
    """工具集规模有下限：数量骤降说明注册列表被误改或模块导入失败"""
    assert len(TOOL_LIST) >= 100


def test_every_defined_tool_is_registered():
    """每个 @tool 定义都必须出现在 tools 列表里，否则 LLM 永远看不到它"""
    defined = _defined_tools()
    registered = {getattr(t, "name", None) for t in TOOL_LIST}
    missing = sorted(set(defined) - registered)
    assert not missing, f"定义了但未注册到 tools 列表：{missing}"


def test_no_duplicate_registration():
    """重复注册会让同一工具多次进入 LLM 的选择空间，放大误调用概率"""
    names = [getattr(t, "name", None) for t in TOOL_LIST]
    dup = sorted({n for n in names if names.count(n) > 1})
    assert not dup, f"tools 列表中存在重复项：{dup}"


def test_every_tool_has_docstring():
    """docstring 就是 LLM 的工具说明书，缺描述的工具会被错误选用或不敢用"""
    no_desc = sorted(
        getattr(t, "name", "") for t in TOOL_LIST if not (t.description or "").strip()
    )
    assert not no_desc, f"缺少描述的工具：{no_desc}"


def test_every_tool_has_unique_name():
    """重名会让 LangGraph 的工具路由不确定：同名后注册者覆盖先注册者"""
    names = _defined_tools().keys()
    assert len(names) == len(set(names))


def test_tool_count_matches_definition_count():
    """列表长度与 @tool 定义数一致，防止有人只加定义不加注册"""
    assert len(TOOL_LIST) == len(_defined_tools())


@pytest.mark.parametrize("tool_name", [
    "spatial_buffer", "spatial_centroid", "export_layer", "focus_map",
    "inspect_satellite_image", "discover_gis_data", "execute_python",
])
def test_core_tools_are_reachable(tool_name):
    """核心能力工具必须始终可被选中——改名/漏注册时这里会先炸"""
    registered = {getattr(t, "name", None) for t in TOOL_LIST}
    assert tool_name in registered
