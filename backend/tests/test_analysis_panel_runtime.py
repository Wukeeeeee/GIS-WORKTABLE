# -*- coding: utf-8 -*-
"""Runtime smoke test for the analysis-tools panel (frontend/js/analysis_tools.js).

The panel is pure client code, so the existing wiring tests in
``test_analysis_panel_wiring.py`` only check the source text. This test goes one
step further and actually *executes* the panel bootstrap inside Node with a tiny
DOM stub, which catches runtime errors such as identifiers used before their
``var`` declaration (hoisting) that silently break every menu item.

Skipped when Node.js is not available.
"""
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HARNESS = os.path.join(ROOT, "backend", "tests", "analysis_panel_dom_harness.js")
JS_PATH = os.path.join(ROOT, "frontend", "js", "analysis_tools.js")

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
def test_analysis_panel_bootstrap_runs_without_error():
    assert os.path.isfile(HARNESS), HARNESS
    assert os.path.isfile(JS_PATH), JS_PATH
    proc = subprocess.run(
        [NODE, HARNESS, JS_PATH],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, (
        "analysis panel bootstrap crashed:\n%s\n%s" % (proc.stdout, proc.stderr)
    )
    assert "OK" in proc.stdout, proc.stdout + proc.stderr