# -*- coding: utf-8 -*-
"""空间插值（IDW / RBF）测试

插值最容易出的不是崩溃，而是"图出来了一切正常、但方向/取值是错的"。
这里用南低北高的非对称数据把方向钉死。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from backend.services import tools as T
from backend.services.tools import (
    spatial_interpolate, _register_layer, _registered_layers, reset_state,
    _pending_layer_ops,
)


# 南（y=0.0）低值 -> 北（y=0.10）高值，南北非对称
_PROFILE_POINTS = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"value": 0.0}, "geometry": {"type": "Point", "coordinates": [0.000, 0.00]}},
        {"type": "Feature", "properties": {"value": 10.0}, "geometry": {"type": "Point", "coordinates": [0.001, 0.02]}},
        {"type": "Feature", "properties": {"value": 50.0}, "geometry": {"type": "Point", "coordinates": [0.002, 0.05]}},
        {"type": "Feature", "properties": {"value": 90.0}, "geometry": {"type": "Point", "coordinates": [0.003, 0.08]}},
        {"type": "Feature", "properties": {"value": 100.0}, "geometry": {"type": "Point", "coordinates": [0.004, 0.10]}},
    ],
}


@pytest.fixture(autouse=True)
def _clean():
    reset_state()
    _registered_layers.clear()
    _pending_layer_ops.clear()
    yield
    reset_state()
    _registered_layers.clear()
    _pending_layer_ops.clear()


def _run_interp(**kw):
    _register_layer("prof", _PROFILE_POINTS)
    r = spatial_interpolate.invoke({"layer_name": "prof", "field": "value", **kw})
    return r


def _overlay_path():
    """取本轮插值生成的 PNG 绝对路径"""
    ops = [o for o in _pending_layer_ops if o.get("action") == "dem_result"]
    assert ops, f"没有产生 dem_result 叠加操作，当前：{_pending_layer_ops}"
    op = ops[0]
    rel = op["url"].replace("/output/", "")
    path = os.path.join(T._temp_output_dir, rel)
    assert os.path.isfile(path), f"叠加图未落盘：{path}"
    return path, op


class TestInterpolateBasics:
    def test_idw_produces_overlay(self):
        r = _run_interp(method="idw", resolution=30)
        assert "IDW" in r
        _overlay_path()

    def test_rbf_produces_overlay(self):
        r = _run_interp(method="rbf", resolution=30)
        assert "RBF" in r
        _overlay_path()

    def test_unknown_method_rejected(self):
        r = _run_interp(method="kriging", resolution=30)
        assert "不支持" in r

    def test_non_point_layer_rejected(self):
        _register_layer("poly", {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature", "properties": {"value": 1},
                "geometry": {"type": "Polygon",
                             "coordinates": [[[0, 0], [0.02, 0], [0.02, 0.02], [0, 0.02], [0, 0]]]},
            }],
        })
        r = spatial_interpolate.invoke({"layer_name": "poly", "field": "value"})
        assert "点要素" in r

    def test_missing_field_rejected(self):
        _register_layer("prof", _PROFILE_POINTS)
        r = spatial_interpolate.invoke({"layer_name": "prof", "field": "不存在"})
        assert "没有字段" in r


class TestInterpolateOrientation:
    def test_output_image_is_north_up(self):
        """回归：meshgrid 曾按 y 递增生成，row 0 是南，
        PNG 交给 Leaflet 叠加后整张图南北翻转（高值区显示在地图下方）。"""
        from PIL import Image
        _run_interp(method="idw", resolution=50)
        path, op = _overlay_path()

        img = np.array(Image.open(path).convert("RGB"))
        h = img.shape[0]
        # viridis：低值深紫（G 通道远小于 B），高值亮黄（G 通道远大于 B）
        top_is_high = img[2, :, 1].mean() > img[2, :, 2].mean()
        bottom_is_low = img[h - 3, :, 1].mean() < img[h - 3, :, 2].mean()
        assert top_is_high and bottom_is_low, (
            "插值图应为北在上：数据北边是高值，图像顶部应偏黄、底部应偏紫")

    def test_bounds_match_north_south_order(self):
        """bounds 必须是 [west, south, east, north]"""
        _run_interp(method="idw", resolution=30)
        _, op = _overlay_path()
        b = op["bounds"]
        assert b[1] < b[3], f"bounds 南北顺序错误：{b}"
        assert b[0] < b[2], f"bounds 东西顺序错误：{b}"


class TestTempOutputDirLifecycle:
    def test_reset_state_initializes_output_dir(self):
        """回归：_temp_output_dir 的注释写着"在 reset_state 时设置"，但代码没做。

        一旦一轮里最先执行的工具是直接写该目录的（如 spatial_interpolate），
        目录还是空串，产物会落到 CWD/uploads，而 URL 指向 /output/...，前端 404。
        """
        reset_state()
        assert T._temp_output_dir, "reset_state 之后 _temp_output_dir 仍为空"
        assert os.path.isdir(T._temp_output_dir)

    def test_interpolate_works_without_prior_setup(self, monkeypatch, tmp_path):
        """把输出目录指向 tmp 后，产物必须落在那儿，而不是 CWD"""
        monkeypatch.setattr(T, "_temp_output_dir", str(tmp_path / "out"))
        _run_interp(method="idw", resolution=20)
        written = list((tmp_path / "out" / "uploads").glob("*.png"))
        assert written, "插值产物没有写到指定的输出目录"
