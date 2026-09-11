# -*- coding: utf-8 -*-
"""结果真实性自检（result_guard）测试

这个模块的作用是拦住"AI 说生成了、磁盘上却没有"的假成功。
它自己必须是确定性的：不会因为模型心情不同而给出不同结论。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from backend.services import result_guard as RG


# ---------------------------------------------------------------- 路径解析

def test_resolve_artifact_path_supports_three_forms():
    """output/x.png、/output/x.png、cache/a/b.png 三种写法都要能解析"""
    a = RG.resolve_artifact_path("output/x.png")
    b = RG.resolve_artifact_path("/output/x.png")
    assert a == b
    assert a.replace("\\", "/").endswith("gis_worktable_output/x.png")
    assert RG.resolve_artifact_path("cache/charts/y.png").replace("\\", "/").endswith("cache/charts/y.png")


def test_resolve_artifact_path_rejects_unknown_and_urls():
    """不属于已知输出目录的路径不参与校验；网络 URL 直接跳过"""
    assert RG.resolve_artifact_path("some/random/file.png") is None
    assert RG.resolve_artifact_path("https://example.com/a.png") is None
    assert RG.resolve_artifact_path("") is None


# ---------------------------------------------------------------- 路径抽取

def test_extract_output_paths_from_reply_text():
    text = "结果已保存为 output/gz_map.png，另见 /cache/charts/ndvi_2026.png。"
    paths = RG.extract_output_paths(text)
    assert "output/gz_map.png" in paths
    assert "cache/charts/ndvi_2026.png" in paths


def test_extract_output_paths_ignores_prose_and_urls():
    """普通叙述和网页链接不能被误判成本地产物路径"""
    text = "请参考 https://example.com/report.png 与 output 目录下的说明，我没有生成文件。"
    assert RG.extract_output_paths(text) == []


# ---------------------------------------------------------------- 主校验

def test_verify_flags_missing_claimed_file():
    """回复里声称存在的产物文件找不到 → 必须报不出来"""
    text = "已生成专题图 output/definitely_not_exists_9527.png"
    res = RG.verify_result(text, {})
    assert res["ok"] is False
    assert "output/definitely_not_exists_9527.png" in res["missing_paths"]
    assert len(res["issues"]) >= 1


def test_verify_flags_zero_byte_file(tmp_path, monkeypatch):
    """0 字节文件等于没生成，必须同"不存在"一样被拦下

    用 tmp 目录替换真实输出目录，测试不写项目本体、也不依赖运行环境的可写权限。
    """
    cache_dir = tmp_path / "cache"
    (cache_dir / "charts").mkdir(parents=True)
    monkeypatch.setitem(RG._OUTPUT_DIRS, "cache", str(cache_dir))
    (cache_dir / "charts" / "zero.png").write_bytes(b"")

    res = RG.verify_result("图已生成 /cache/charts/zero.png", {})
    assert res["ok"] is False
    assert "cache/charts/zero.png" in res["missing_paths"]


def test_verify_passes_when_file_really_exists(tmp_path, monkeypatch):
    """真实存在的文件不应误报（避免把自检做成噪音制造机）"""
    cache_dir = tmp_path / "cache"
    (cache_dir / "charts").mkdir(parents=True)
    monkeypatch.setitem(RG._OUTPUT_DIRS, "cache", str(cache_dir))
    (cache_dir / "charts" / "real.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 512)

    res = RG.verify_result("图已生成 /cache/charts/real.png", {})
    assert res["ok"] is True
    assert res["missing_paths"] == []


def test_verify_flags_broken_image_url():
    """待推送图片的 URL 指向不存在的文件 → 前端必然裂图"""
    pending = {"images": [{"url": "/output/nope_9527.png", "type": "png"}]}
    res = RG.verify_result("", pending)
    assert res["ok"] is False
    assert "/output/nope_9527.png" in res["broken_images"]


def test_verify_skips_inline_html_image():
    """HTML 图片是内联内容（文件已被读取后删除），不应判为缺失"""
    pending = {"images": [{"url": "/output/page.html", "type": "html", "content": "<html></html>"}]}
    res = RG.verify_result("", pending)
    assert res["broken_images"] == []


def test_verify_flags_layer_without_geojson():
    """没有矢量数据的图层无法在地图上显示"""
    pending = {"layers": [{"name": "空图层", "geojson": None}]}
    res = RG.verify_result("", pending)
    assert res["ok"] is False
    assert "空图层" in res["empty_layers"]


def test_verify_ok_on_clean_payload():
    pending = {
        "layers": [{"name": "ok", "geojson": {"type": "FeatureCollection", "features": []}}],
        "images": [],
    }
    res = RG.verify_result("纯文本回复，没有提到任何文件。", pending)
    assert res["ok"] is True
    assert res["issues"] == []


# ---------------------------------------------------------------- 提示文本

def test_build_guard_note_empty_when_passed():
    assert RG.build_guard_note({"ok": True, "issues": []}) == ""


def test_build_guard_note_lists_issues_and_caps_them():
    issues = [f"问题-{i}" for i in range(8)]
    note = RG.build_guard_note({"ok": False, "issues": issues})
    assert "结果真实性自检" in note
    assert "问题-0" in note
    assert "问题-4" in note          # 展示上限 5 条
    assert "问题-6" not in note
    assert "另有 3 项" in note

    few = RG.build_guard_note({"ok": False, "issues": ["只有一个"]})
    assert "另有" not in few


# ---------------------------------------------------------------- apply_guard（graph 实际调用入口）

def test_apply_guard_appends_note_to_failed_reply():
    text = "已生成专题图 output/missing_9527.png"
    out, check = RG.apply_guard(text, {})
    assert check["ok"] is False
    assert out.startswith(text)          # 原话保留
    assert "结果真实性自检" in out         # 并附上明确不通过说明


def test_apply_guard_keeps_text_intact_when_passed():
    text = "纯文本回复，没有提到任何产物。"
    out, check = RG.apply_guard(text, {})
    assert out == text
    assert check["ok"] is True


def test_apply_guard_handles_none_text():
    out, check = RG.apply_guard(None, {"images": [{"url": "/output/x.png", "type": "png"}]})
    assert isinstance(out, str)
    assert check["ok"] is False          # 坏图片仍应被抓出来


# ---------------------------------------------------------------- 脆弱输入

def test_verify_handles_none_and_empty():
    assert RG.verify_result(None, None)["ok"] is True
    assert RG.verify_result("", {})["ok"] is True


def test_verify_handles_malformed_pending_items():
    """工具偶尔塞非 dict 进来时不能把整轮结果搞崩"""
    res = RG.verify_result("", {"images": ["not-a-dict"], "layers": [None]})
    assert res["ok"] is True
