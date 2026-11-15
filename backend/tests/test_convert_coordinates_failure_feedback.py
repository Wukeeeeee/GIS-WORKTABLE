import pytest

from backend.services import tools


def test_web_mercator_target_rejects_geographic_coordinate_outside_area():
    result = tools.convert_coordinates.invoke({
        "coords": "0,89", "source_crs": "wgs84", "target_crs": "web_mercator",
    })

    assert result.startswith("坐标转换失败")
    assert "85.06" in result
    assert tools._tool_result_failed("convert_coordinates", result)


@pytest.mark.parametrize("target_crs", ["wgs84", "EPSG:3857"])
def test_web_mercator_source_rejects_coordinate_outside_area(target_crs):
    result = tools.convert_coordinates.invoke({
        "coords": "0,30240971.958386",
        "source_crs": "EPSG:3857",
        "target_crs": target_crs,
    })

    assert result.startswith("坐标转换失败")
    assert "85.06" in result
    assert tools._tool_result_failed("convert_coordinates", result)


def test_web_mercator_target_accepts_coordinate_inside_area():
    result = tools.convert_coordinates.invoke({
        "coords": "0,85.05", "source_crs": "wgs84", "target_crs": "web_mercator",
    })

    assert result.startswith("wgs84→web_mercator:")
    assert "20050000" not in result
