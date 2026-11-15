import pytest

from backend.services import tools


@pytest.mark.parametrize(
    ("coordinates", "expected"),
    [
        ((float("nan"), 0, 1, 1), "输入坐标必须是有限数值"),
        ((float("inf"), 0, 1, 1), "输入坐标必须是有限数值"),
        ((181, 0, 1, 1), "输入坐标超出 WGS-84 范围"),
        ((0, 91, 1, 1), "输入坐标超出 WGS-84 范围"),
    ],
)
def test_invalid_distance_coordinates_are_classified_as_failure(coordinates, expected):
    arguments = dict(zip(("lon1", "lat1", "lon2", "lat2"), coordinates))

    result = tools.measure_distance.invoke(arguments)

    assert result.startswith(expected)
    assert tools._tool_result_failed("measure_distance", result)


def test_valid_distance_is_not_classified_as_failure():
    result = tools.measure_distance.invoke({"lon1": 0, "lat1": 0, "lon2": 1, "lat2": 1})

    assert result.startswith("距离：")
    assert not tools._tool_result_failed("measure_distance", result)
