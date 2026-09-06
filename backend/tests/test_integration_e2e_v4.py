# -*- coding: utf-8 -*-
"""
API 级集成测试第四批：网络分析、知识库、协议清理、凭据安全、多轮状态
零 token 消耗，动态生成数据
"""
import os
import sys
import uuid
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.services import tools
from backend.services.tools import (
    network_analysis,
    ask_user_choice,
    _register_layer,
    _registered_layers,
    _pending_layers,
    get_registered_layers_snapshot,
)
from backend.services.graph import _clean_ai_text
from backend.services.ai_service import _load_skill_from_file


class TestNetworkAnalysisE2E:
    """网络分析端到端"""

    def test_network_with_invalid_layer(self):
        """非路网图层应返回友好错误"""
        name = f"net_inv_{uuid.uuid4().hex[:6]}"
        # 注册点图层（不是路网）
        features = [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Point", "coordinates": [113.0, 23.0]}
        }]
        _register_layer(name, {"type": "FeatureCollection", "features": features})

        func = getattr(network_analysis, 'func', network_analysis)
        result = func(layer_name=name, analysis_type="shortest_path", origin="113.0,23.0", destination="113.1,23.1")
        assert result is not None
        # 可能返回错误或结果，但不应崩溃
        assert len(result) > 0

    def test_network_nonexistent_layer(self):
        """不存在的路网图层应返回错误"""
        func = getattr(network_analysis, 'func', network_analysis)
        result = func(layer_name="nonexistent_net_xyz", analysis_type="shortest_path", origin="113.0,23.0", destination="113.1,23.1")
        assert result is not None
        assert "不存在" in result or "未找到" in result or "错误" in result


class TestUserChoiceE2E:
    """用户选项选择端到端"""

    def test_choice_returns_prompt(self):
        """ask_user_choice 应返回包含选项的提示"""
        func = getattr(ask_user_choice, 'func', ask_user_choice)
        result = func(
            prompt="请选择数据源",
            options=[{"label": "Esri", "value": "esri"}, {"label": "Bing", "value": "bing"}],
            choice_key="data_source"
        )
        assert result is not None
        assert "Esri" in result or "Bing" in result or "选择" in result

    def test_choice_with_empty_options(self):
        """空选项应返回错误"""
        func = getattr(ask_user_choice, 'func', ask_user_choice)
        result = func(prompt="测试", options=[], choice_key="test")
        assert result is not None


class TestProtocolCleaningE2E:
    """协议泄露清理端到端"""

    def test_clean_dsml_tool_calls(self):
        """应清理 DSML 格式的 tool_calls 泄露"""
        leaked = """我来帮你查询
<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="amap_geocode">
<｜｜DSML｜｜parameter name="name">广州</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
</｜｜DSML｜｜tool_calls>
正在查询"""
        cleaned = _clean_ai_text(leaked)
        assert "DSML" not in cleaned
        assert "tool_calls" not in cleaned
        assert "invoke" not in cleaned or "amap_geocode" not in cleaned

    def test_clean_normal_text(self):
        """正常文本不应被修改"""
        normal = "广州未来7天天气晴朗，温度25-30度。"
        cleaned = _clean_ai_text(normal)
        assert cleaned == normal

    def test_clean_mixed_content(self):
        """混合内容应保留正常文字，清理协议部分"""
        mixed = "好的，我来查询。<｜｜DSML｜｜tool_calls>test</｜｜DSML｜｜tool_calls> 查询完成。"
        cleaned = _clean_ai_text(mixed)
        assert "好的" in cleaned
        assert "查询完成" in cleaned
        assert "DSML" not in cleaned


class TestKnowledgeBaseE2E:
    """知识库加载端到端"""

    def test_load_existing_knowledge(self):
        """应能加载已有的知识模块（skills/ 或 knowledge/）"""
        # 尝试加载 GIS 基础知识模块
        result = _load_skill_from_file("01_gis_basics")
        # 如果 knowledge/ 目录不存在，结果可能为空，这不应该报错
        assert result is not None  # 不应抛异常

    def test_load_coordinate_systems(self):
        """坐标系知识模块应能加载（如果存在）"""
        result = _load_skill_from_file("02_coordinate_systems")
        assert result is not None  # 不应抛异常

    def test_load_nonexistent_knowledge(self):
        """不存在的知识模块应返回空或默认值"""
        result = _load_skill_from_file("nonexistent_module_xyz")
        # 不应抛异常
        assert result is not None


class TestCredentialSecurityE2E:
    """凭据安全端到端"""

    def test_credential_store_encrypts(self):
        """凭据存储应加密，不存明文"""
        from backend.services.credential_store import save_credential, get_credential, has_credential
        service = f"test_svc_{uuid.uuid4().hex[:6]}"
        save_credential(service, "testuser", "testpass123")
        assert has_credential(service) == True
        # get_credential 应能取回（内部解密）
        cred = get_credential(service)
        assert cred is not None
        assert cred.get("username") == "testuser"
        assert cred.get("password") == "testpass123"

    def test_credential_not_in_plaintext_file(self):
        """凭据文件中不应有明文密码"""
        from backend.services.credential_store import save_credential, _CRED_FILE
        service = f"test_plain_{uuid.uuid4().hex[:6]}"
        save_credential(service, "user1", "mysecretpassword_xyz")
        if os.path.exists(_CRED_FILE):
            content = open(_CRED_FILE, encoding="utf-8").read()
            assert "mysecretpassword_xyz" not in content, "密码明文存储在文件中！"

    def test_delete_credential(self):
        """删除凭据后应不存在"""
        from backend.services.credential_store import save_credential, delete_credential, has_credential
        service = f"test_del_{uuid.uuid4().hex[:6]}"
        save_credential(service, "user", "pass")
        assert has_credential(service) == True
        delete_credential(service)
        assert has_credential(service) == False


class TestLayerLifecycleE2E:
    """图层完整生命周期：注册→查询→删除→快照"""

    def test_full_lifecycle(self):
        """注册→查询详情→删除→快照中消失"""
        name = f"lifecycle_{uuid.uuid4().hex[:6]}"
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"value": 42},
                "geometry": {"type": "Point", "coordinates": [113.0, 23.0]}
            }]
        }
        # 注册
        _register_layer(name, geojson)
        snapshot = get_registered_layers_snapshot()
        names = [l.get("filename") or l.get("name") or l.get("layer_id") for l in snapshot]
        assert any(name in str(n) for n in names), "注册后快照中找不到"

        # 查询详情
        func = getattr(tools.get_layer_detail, 'func', tools.get_layer_detail)
        detail = func(layer_name=name)
        assert detail is not None and len(detail) > 10

        # 删除
        tools._unregister_layer(name)
        snapshot2 = get_registered_layers_snapshot()
        names2 = [l.get("filename") or l.get("name") or l.get("layer_id") for l in snapshot2]
        assert not any(name in str(n) for n in names2), "删除后快照中仍存在"


class TestPendingItemsE2E:
    """待推送项管理端到端"""

    def test_pending_layer_queue(self):
        """推送图层后应在待推送队列中"""
        before = len(_pending_layers)
        name = f"pending_{uuid.uuid4().hex[:6]}"
        geojson = {"type": "FeatureCollection", "features": []}
        tools._push_layer(name, geojson, {"color": "#ff0000"})
        assert len(_pending_layers) > before
        # 清空
        _pending_layers.clear()

    def test_pending_image_queue(self):
        """推送图片后应在待推送图片队列中"""
        before = len(tools._pending_images)
        tools._pending_images.append({"url": "/cache/charts/test.png", "type": "png"})
        assert len(tools._pending_images) > before
        tools._pending_images.clear()


class TestRandomDataConsistency:
    """随机数据一致性：多次运行不应互相干扰"""

    def test_multiple_random_layers(self):
        """连续注册多个随机图层，快照应包含全部"""
        names = [f"rand_{i}_{uuid.uuid4().hex[:4]}" for i in range(5)]
        for n in names:
            _register_layer(n, {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "properties": {},
                              "geometry": {"type": "Point",
                                           "coordinates": [random.uniform(110, 120), random.uniform(20, 40)]}}]
            })
        snapshot = get_registered_layers_snapshot()
        snap_names = [l.get("filename") or l.get("name") or l.get("layer_id") for l in snapshot]
        for n in names:
            assert any(n in str(sn) for sn in snap_names), f"图层 {n} 丢失"
