# -*- coding: utf-8 -*-
"""Regression guard for the floating-panel "close then reopen shows nothing" bug.

``GIS.workspace.preparePanel`` registers a close handler that hides the panel
element itself with ``hidden`` + ``is-hidden`` + inline ``display:none !important``.
Every panel module's open path only unhides its *container* and then calls
``GIS.workspace.expandPanel(id)``, so ``expandPanel`` has to clear that close
state. Without it, closing a panel with the X button makes it permanently blank
even though the menu item can be clicked again.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKSPACE_JS = os.path.join(ROOT, "frontend", "js", "workspace.js")
JS_DIR = os.path.join(ROOT, "frontend", "js")

FLOATING_PANELS = [
    "spatialPanel",
    "spatialStatsPanel",
    "networkPanel",
    "rasterToolsPanel",
    "analysisToolsPanel",
    "debugPanel",
    "historyPanel",
    "layerInspector",
]


@pytest.fixture(scope="module")
def workspace_text():
    with open(WORKSPACE_JS, "r", encoding="utf-8") as f:
        return f.read()


def _function_body(text, name):
    m = re.search(r"function\s+%s\s*\([^)]*\)\s*\{" % name, text)
    assert m, "function %s() not found" % name
    start = m.end() - 1
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError("unbalanced braces while parsing %s()" % name)


def test_prepare_panel_close_still_sets_hidden_state(workspace_text):
    body = _function_body(workspace_text, "preparePanel")
    assert "classList.add('is-hidden')" in body
    assert "setAttribute('hidden'" in body
    assert "important" in body


def test_expand_panel_clears_close_state(workspace_text):
    body = _function_body(workspace_text, "expandPanel")
    assert "classList.remove('is-hidden')" in body, \
        "expandPanel must drop the is-hidden class left by the close button"
    assert "removeAttribute('hidden')" in body, \
        "expandPanel must drop the hidden attribute left by the close button"
    assert "removeProperty('display')" in body, \
        "expandPanel must drop the inline display:none!important left by the close button"


def test_every_prepared_panel_is_also_expanded_on_open():
    js = {}
    for name in os.listdir(JS_DIR):
        if not name.endswith(".js"):
            continue
        with open(os.path.join(JS_DIR, name), "r", encoding="utf-8") as f:
            js[name] = f.read()
    for panel in FLOATING_PANELS:
        owner = [n for n, t in js.items() if "preparePanel('%s'" % panel in t]
        assert owner, "no module prepares panel %s" % panel
        for name in owner:
            if panel == "featurePanel":  # Cesium clears hidden state itself
                continue
            literal = "expandPanel('%s')" % panel in js[name]
            dynamic = "expandPanel(panelId)" in js[name] or "expandPanel(root.id)" in js[name]
            assert literal or dynamic, \
                "%s opens %s but never calls expandPanel(...)" % (name, panel)