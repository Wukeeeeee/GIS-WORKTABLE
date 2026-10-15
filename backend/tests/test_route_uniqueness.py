# -*- coding: utf-8 -*-
"""路由唯一性守门测试

背景：两个开发者各自添加了 POST /api/tools/invoke，FastAPI 只会命中先注册的那个，
后者静默失效——没有报错、没有警告，因此现有任何测试都抓不到。
这里把“同路径 + 同方法只能存在一个处理器”钉成测试。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _collect_routes():
    from backend.main import app
    seen = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or []
        if not path:
            continue
        for method in methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            seen.setdefault((path, method), []).append(
                getattr(getattr(route, "endpoint", None), "__name__", "?")
            )
    return seen


def test_no_duplicate_route_path_and_method():
    """同一个 path+method 被注册两次时，只有先注册的生效，后者集体死代码"""
    seen = _collect_routes()
    dup = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dup, f"存在重复注册的路由（后者被静默遮蔽）：{dup}"


def test_tools_invoke_single_handler():
    """直接回归保护：/api/tools/invoke 只能有一个 POST 处理器"""
    seen = _collect_routes()
    hits = seen.get(("/api/tools/invoke", "POST"), [])
    assert len(hits) == 1, f"/api/tools/invoke 共有 {len(hits)} 个 handler：{hits}"


def test_tools_invoke_returns_layer_channels():
    """该端点必须返回图层通道，否则前端面板拿不到图层产物"""
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app)
    resp = client.post("/api/tools/invoke", json={"name": "get_registered_layers", "arguments": {}})
    assert resp.status_code == 200
    data = resp.json()
    assert "response" in data, f"缺少 response 字段: {sorted(data.keys())}"
    for key in ("layers", "layer_ops", "images"):
        assert key in data, f"缺少 {key} 字段: {sorted(data.keys())}"


def test_tools_invoke_unknown_tool_is_404():
    """未知工具应返回 404，而不是 200 + ok:false"""
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app)
    resp = client.post("/api/tools/invoke", json={"name": "no_such_tool_xyz", "arguments": {}})
    assert resp.status_code == 404
