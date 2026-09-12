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


def _ast_tool_definitions(path):
    """用 AST 扫出文件里所有被 @tool 装饰的函数名（按出现顺序，不去重）。

    为什么需要它：`vars(T)` 是按名字索引的字典，两个同名 def 只会剩一个，
    "后定义的把先定义的静默覆盖"这种问题靠运行时对象查不出来，只能看源码。
    """
    import ast
    tree = ast.parse(open(path, encoding="utf-8").read())
    names = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if any(isinstance(d, ast.Name) and d.id == "tool" for d in node.decorator_list):
            names.append(node.name)
    return names


def test_tools_module_imports_and_has_substantial_tools():
    """工具集规模有下限：数量骤降说明注册列表被误改或模块导入失败"""
    assert len(TOOL_LIST) >= 100


def test_every_defined_tool_is_registered():
    """每个 @tool 定义都必须出现在 tools 列表里，否则 LLM 永远看不到它"""
    defined = _defined_tools()
    registered = {getattr(t, "name", None) for t in TOOL_LIST}
    missing = sorted(set(defined) - registered)
    assert not missing, f"定义了但未注册到 tools 列表：{missing}"


def test_no_function_defined_twice():
    """同名函数被定义两次时，后一个会静默覆盖前一个——运行时查不出来，只能扫源码"""
    names = _ast_tool_definitions(T.__file__)
    dup = sorted({n for n in names if names.count(n) > 1})
    assert not dup, f"以下 @tool 函数被重复定义（前一个会被静默覆盖）：{dup}"


def test_source_definition_count_matches_registry():
    """源码里 @tool 的定义数必须与注册数一致（防"加了定义忘了注册"）"""
    names = _ast_tool_definitions(T.__file__)
    assert len(names) == len(TOOL_LIST), (
        f"源码定义 {len(names)} 个 @tool，tools 列表注册 {len(TOOL_LIST)} 个")


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


# ============================================================
# 图层通道守卫：禁止绕过 _push_layer / _register_layer 手写图层
# ============================================================
# 背景：extract_contours 曾手写 _pending_layers.append({type,features,name}) 与
# _registered_layers[name]={type,name}，绕开统一接口——前端读不到 geojson（不渲染）、
# 后续工具 _layer_to_gdf 报「图层为空」，但工具本身仍返回“成功”。
# 这类 bug 的症状在工具之外，靠单个工具的单测抓不到，只能从源码结构上禁掉。

def _layer_channel_violations(path):
    """扫描对 _pending_layers / _registered_layers 的手写操作，返回 [(lineno, desc)]。

    规则：
    - `_pending_layers.append(...)` 只允许出现在 `_push_layer` 内；
    - 整表赋值 `_registered_layers[x] = ...` 只允许出现在 `_register_layer` 内，
      或 `= _registered_layers.pop(...)`（重命名搬移）。
    合法的 `_registered_layers[x]["geojson"] = ...`（键更新）不在扫描范围内。
    """
    import ast
    tree = ast.parse(open(path, encoding="utf-8").read())

    class V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []
            self.bad = []

        def _cur(self):
            return self.stack[-1] if self.stack else "<module>"

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node):
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr == "append"
                    and isinstance(f.value, ast.Name) and f.value.id == "_pending_layers"
                    and self._cur() != "_push_layer"):
                self.bad.append((node.lineno,
                                 f"_pending_layers.append() 出现在 {self._cur()}（应改用 _push_layer）"))
            self.generic_visit(node)

        def visit_Assign(self, node):
            for tgt in node.targets:
                if (isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "_registered_layers"):
                    v = node.value
                    is_pop = (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                              and v.func.attr == "pop"
                              and isinstance(v.func.value, ast.Name)
                              and v.func.value.id == "_registered_layers")
                    if self._cur() != "_register_layer" and not is_pop:
                        self.bad.append((node.lineno,
                                         f"_registered_layers[x] = ... 整表赋值出现在 {self._cur()}"
                                         "（应改用 _register_layer）"))
            self.generic_visit(node)

    v = V()
    v.visit(tree)
    return v.bad


def test_no_manual_layer_channel_bypass():
    """禁止绕过 _push_layer / _register_layer 手写图层通道（否则前端不渲染/后续工具读空）"""
    bad = _layer_channel_violations(T.__file__)
    assert not bad, "存在绕过统一图层接口的写法：" + "; ".join(f"L{ln} {d}" for ln, d in bad)


def test_layer_channel_guard_detects_violation():
    """自检：守卫本身必须能抓到违规写法，否则它是空的"""
    import tempfile
    bad_src = (
        "def _push_layer(n, g):\n"
        "    _pending_layers.append({'name': n})\n"
        "def bad_tool():\n"
        "    _pending_layers.append({'type': 'FeatureCollection'})\n"
        "    _registered_layers['x'] = {'type': 'FeatureCollection', 'name': 'x'}\n"
        "    _registered_layers['x']['geojson'] = {}\n"
        "    return 'ok'\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(bad_src)
        p = f.name
    try:
        bad = _layer_channel_violations(p)
        lines = {ln for ln, _ in bad}
        assert 4 in lines, f"漏报 _pending_layers.append 越权（返回 {bad}）"
        assert 5 in lines, f"漏报 _registered_layers 整表赋值（返回 {bad}）"
        assert 6 not in lines, "键更新 _registered_layers[x]['geojson'] 被误报"
        assert 2 not in lines, "_push_layer 内的合法 append 被误报"
    finally:
        os.unlink(p)
