"""Check each production analysis-panel entry against the registered tool schema."""
import re
from pathlib import Path

import pytest

from backend.services.tools import tools


SOURCE = (Path(__file__).resolve().parents[2] / 'frontend/js/analysis_tools.js').read_text(encoding='utf-8')
ENTRIES = re.findall(r"\{ id: '([^']+)',[^\n]+?tool: '([^']+)'([^\n]+)\},", SOURCE)
REGISTRY = {tool.name: tool for tool in tools}


def test_the_contract_scan_covers_all_twenty_analysis_entries():
    assert len(ENTRIES) == 20


@pytest.mark.parametrize('entry_id,tool_name,configuration', ENTRIES, ids=[entry[0] for entry in ENTRIES])
def test_analysis_panel_layer_arguments_exist_on_the_registered_tool(entry_id, tool_name, configuration):
    assert tool_name in REGISTRY, f'{entry_id} points to an unregistered tool'
    explicit = re.search(r'layers: \[([^\]]*)\]', configuration)
    arguments = re.findall(r"'([^']+)'", explicit.group(1)) if explicit else ['layer_name']
    assert set(arguments) <= set(REGISTRY[tool_name].args)
