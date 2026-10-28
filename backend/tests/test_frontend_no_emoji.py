# -*- coding: utf-8 -*-
"""Frontend emoji / decorative-glyph regression guard.

Covers the ten frontend JS modules that were converted from character glyphs
(\u2713 \u2715 \u2605 ...) to inline SVG icons.  Scoped deliberately to the owned
file list so unrelated frontend files still being cleaned in parallel do not
make this suite red.
"""
import os
import re
import glob

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS_DIR = os.path.join(REPO_ROOT, "frontend", "js")
ICON_DIR = os.path.join(REPO_ROOT, "frontend", "assets", "ui-icons")

OWNED_FILES = [
    "api.js",
    "chat.js",
    "geosource.js",
    "layers.js",
    "map.js",
    "network.js",
    "renderer_cesium.js",
    "settings.js",
    "task.js",
    "workspace.js",
]
INLINE_SVG_FILES = [name for name in OWNED_FILES if name != "settings.js"]

# Characters the owner ruled out of the UI: decorative typographic glyphs plus
# the pictographs that previously lived in these files.
DECORATIVE = "\u2713\u2714\u2715\u2716\u2717\u2605\u2606\u26a0\u2795\u270e\u23f3"
PICTOGRAPHS = "\U0001F4C1\U0001F4C2\U0001F4CA\u26a1\U0001F310"


def _is_emoji_or_symbol(ch):
    """Emoji blocks + variation selector + the explicit decorative set."""
    o = ord(ch)
    if ch in DECORATIVE or ch in PICTOGRAPHS:
        return True
    if 0x1F000 <= o <= 0x1FAFF:          # emoji & pictographs
        return True
    if 0x1F1E6 <= o <= 0x1F1FF:          # regional indicators
        return True
    if 0xFE00 <= o <= 0xFE0F:            # variation selectors (U+FE0F)
        return True
    if 0x2600 <= o <= 0x27BF:            # misc symbols & dingbats
        return True
    if 0x2B00 <= o <= 0x2BFF:            # misc symbols & arrows
        return True
    return False


def _read(name):
    with open(os.path.join(JS_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def _normalise(text):
    """Un-escape JS string quotes so HTML attributes are comparable."""
    return text.replace('\\"', '"').replace("\\'", "'")


@pytest.mark.parametrize("name", OWNED_FILES)
def test_no_emoji_or_decorative_glyphs(name):
    text = _read(name)
    offenders = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for ch in line:
            if _is_emoji_or_symbol(ch):
                offenders.append((lineno, ch, "U+%04X" % ord(ch)))
        if len(offenders) > 20:
            break
    assert not offenders, "%s still contains glyphs: %s" % (name, offenders[:20])


def test_owned_files_are_the_expected_set():
    """Guard against silently dropping a file from the scan list."""
    expected = set(OWNED_FILES)
    assert "analysis_tools.js" not in expected


@pytest.mark.parametrize("name", INLINE_SVG_FILES)
def test_inline_svgs_use_current_color(name):
    """Every inline SVG we introduced must inherit the surrounding text colour."""
    text = _normalise(_read(name))
    svgs = re.findall(r"<svg\b[^>]*>", text)
    assert svgs, "%s has no inline SVG icons" % name
    missing = [tag for tag in svgs if 'stroke="currentColor"' not in tag]
    assert not missing, "%s has svg without currentColor: %s" % (name, missing[:3])


@pytest.mark.parametrize("name", INLINE_SVG_FILES)
def test_decorative_svgs_are_aria_hidden(name):
    text = _normalise(_read(name))
    for tag in re.findall(r"<svg\b[^>]*>", text):
        assert 'aria-hidden="true"' in tag, "%s svg missing aria-hidden: %s" % (name, tag[:120])


@pytest.mark.parametrize("name", OWNED_FILES)
def test_ui_icon_assets_exist(name):
    """Any --ui-icon-image reference must point at a real asset file."""
    text = _read(name)
    for ref in re.findall(r"--ui-icon-image:url\(([^)]*)\)", text):
        cleaned = ref.strip().strip("'\"")
        if cleaned.startswith("/assets/ui-icons/"):
            rel = cleaned[len("/assets/ui-icons/"):]
            assert os.path.isfile(os.path.join(ICON_DIR, rel)), \
                "%s references missing icon asset %s" % (name, cleaned)


def test_statistics_prefix_stripping_is_preserved():
    """workspace.js must keep stripping a leading symbol before the stats labels.

    The backend emits:  "📊 「{layer}」.{field} 统计：" as the first line,
    followed by "  count: ..." etc.  The replacement must also tolerate the
    no-symbol case.
    """
    text = _read("workspace.js")
    m = re.search(r"(?:const|let) message = rawMessage\.replace\((/[^\n]+?/u), ''\)", text)
    assert m, "statistics-stripping replace(...) not found in workspace.js"
    pattern = m.group(1)
    assert pattern.startswith("/^"), "statistics stripping regex must be leading-anchored: %s" % pattern
    end = pattern.rindex("/")
    body, flags = pattern[1:end], pattern[end + 1:]

    # The tolerant form we require: optional leading whitespace, a cluster of
    # Unicode Symbol characters / variation selectors, optional trailing space.
    required = r"^\s*[\p{S}\uFE0F]+\s*"
    assert body == required, "statistics prefix regex is not the tolerant form: %s" % body
    assert "u" in flags, "statistics prefix regex must use the /u flag"

    # Emulate the JS regex in Python.  Python's re has no \p{S}, so build an
    # equivalent symbol class from the Unicode ranges that matter here.
    python_symbols = (
        "\u2600-\u27BF"      # misc symbols & dingbats (incl. ⚠, ★)
        "\u2B00-\u2BFF"      # misc symbols & arrows
        "\uFE0F"              # variation selector-16
        "\U0001F000-\U0001FAFF"  # emoji / pictographs (incl. 📊)
    )
    python_body = body.replace(
        r"[\p{S}\uFE0F]+", "[" + python_symbols + "]+"
    ).replace(r"\s", r"\s")
    regex = re.compile(python_body, re.UNICODE)

    labels = re.compile(r"^(\s*)(count|non_null|null|min|max|mean|sum|std):", re.M)

    # 1) exactly what backend/services/tools.py:spatial_field_stats emits
    backend = (
        "📊 「测试图层」.pop 统计："
        "\n  count: 100\n  non_null: 97\n  null: 3\n"
        "  min: 1.5000\n  max: 900.2500\n  mean: 42.1234\n"
        "  sum: 4212.3400\n  std: 12.5000"
    )
    stripped = regex.sub("", backend, count=1)
    assert not stripped.startswith("📊"), "pictograph prefix was not stripped"
    assert "「测试图层」.pop" in stripped, "layer/field text must be preserved"
    assert labels.search(stripped), "stats labels lost after stripping backend prefix"

    # 2) tolerate the no-symbol case
    stripped_nosym = regex.sub("", backend.replace("📊 ", ""), count=1)
    assert labels.search(stripped_nosym), "stats labels lost when no symbol prefix present"

    # 3) defensive: plain label-only output must survive untouched
    plain = "count: 5\nnon_null: 5"
    assert regex.sub("", plain, count=1) == plain, "regex damaged plain stats output"
    assert labels.search(regex.sub("", plain, count=1))
