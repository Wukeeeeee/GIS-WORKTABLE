# -*- coding: utf-8 -*-
"""两阶段数据源选择（choose_option）测试"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import pending_action as pa
from backend.services import tools


def test_ask_user_choice_sets_pending():
    """ask_user_choice 工具应设置 choose_option pending；数据源选择会固定插入 Esri 快速巡检"""
    pa.clear_pending_action("test_choice")
    pa.set_active_session("test_choice")
    result = tools.ask_user_choice.invoke({
        "prompt": "请选择数据源",
        "options": [
            {"label": "地理空间数据云", "configured": False},
            {"label": "Copernicus", "configured": True},
        ],
        "choice_key": "data_source",
    })
    action = pa.get_pending_action("test_choice")
    assert action is not None
    assert action["action"] == "choose_option"
    # 数据源选择会在最前面固定插入 Esri 快速巡检，共 3 个
    assert len(action["options"]) == 3
    assert action["choice_key"] == "data_source"
    assert action["options"][0]["value"] == "esri_quick_inspect"
    assert action["options"][0]["configured"] is True
    assert action["options"][1]["label"] == "地理空间数据云"
    pa.clear_pending_action("test_choice")












