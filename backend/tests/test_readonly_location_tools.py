from backend.services.graph import _tools_for_request


def test_right_click_location_analysis_only_receives_read_only_tools():
    selected = _tools_for_request(read_only_location_analysis=True)
    names = {tool.name for tool in selected}

    assert names == {"reverse_geocode", "search_web", "fetch_weather_data"}
    assert not names.intersection({
        "datav_boundary",
        "fetch_osm_boundary_or_features",
        "layer_control",
        "execute_python",
    })


def test_normal_chat_keeps_the_full_tool_registry():
    assert _tools_for_request() is not _tools_for_request(read_only_location_analysis=True)
    assert len(_tools_for_request()) > len(_tools_for_request(read_only_location_analysis=True))
