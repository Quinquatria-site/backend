"""명세 §5.4 장소 위치 표현: 점(`x`, `y`)과 구역(`area`)."""

import pytest

from ._helpers import create_place, seeded_category

SQUARE = [
    {"x": 10.0, "y": 20.0},
    {"x": 30.5, "y": 20.0},
    {"x": 30.5, "y": 40.25},
    {"x": 10.0, "y": 40.25},
]


async def _polygon(api, area=SQUARE) -> dict:
    response = await api.post("/api/v1/places", json={"is_polygon": True, "area": area})
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_polygon_place_keeps_vertex_order(api) -> None:
    body = await _polygon(api)

    assert (body["is_polygon"], body["x"], body["y"]) == (True, None, None)
    assert body["area"] == SQUARE
    assert (await api.get(f"/api/v1/places/{body['id']}")).json() == body


async def test_polygon_coordinates_round_trip_exactly(api) -> None:
    area = [
        {"x": 0.1, "y": 0.2},
        {"x": 1e-300, "y": -1.7976931348623157e308},
        {"x": 127.123456789012, "y": -36.000000000001},
    ]

    body = await _polygon(api, area)

    assert (await api.get(f"/api/v1/places/{body['id']}")).json()["area"] == area


async def test_point_place_defaults_and_hides_area(api) -> None:
    response = await api.post("/api/v1/places", json={"x": 1.5, "y": 2.5})

    assert response.status_code == 201
    body = response.json()
    assert (body["is_polygon"], body["x"], body["y"], body["area"]) == (
        False,
        1.5,
        2.5,
        None,
    )


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"is_polygon": True}, ["area"]),
        ({"is_polygon": True, "area": SQUARE, "x": 1.0}, ["x"]),
        ({"is_polygon": True, "area": SQUARE, "x": 1.0, "y": 2.0}, ["x", "y"]),
        ({"x": 1.0, "y": 2.0, "area": SQUARE}, ["area"]),
        ({"is_polygon": False, "area": SQUARE}, ["x", "y", "area"]),
        ({}, ["x", "y"]),
    ],
)
async def test_create_with_mismatched_shape_is_422(api, body, fields) -> None:
    response = await api.post("/api/v1/places", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert [row["field"] for row in response.json()["details"]] == fields


@pytest.mark.parametrize(
    "area",
    [
        [],
        SQUARE[:2],
        [{"x": 1.0}, {"x": 2.0, "y": 0.0}, {"x": 3.0, "y": 1.0}],
        [{"x": 1.0, "y": None}, *SQUARE[:2]],
        [{"x": "1.0", "y": 0.0}, *SQUARE[:2]],
        [{"x": 1.0, "y": 0.0, "z": 0.0}, *SQUARE[:2]],
        [[1.0, 0.0], [2.0, 0.0], [3.0, 1.0]],
        [None, *SQUARE[:2]],
    ],
)
async def test_invalid_area_is_422(api, area) -> None:
    response = await api.post("/api/v1/places", json={"is_polygon": True, "area": area})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("value", ["true", 1, None])
async def test_is_polygon_must_be_a_boolean(api, value) -> None:
    response = await api.post(
        "/api/v1/places", json={"is_polygon": value, "area": SQUARE}
    )

    assert response.status_code == 422


async def test_patch_turns_point_into_polygon(api) -> None:
    category = await seeded_category(api)
    place = await create_place(api, category["id"])

    response = await api.patch(
        f"/api/v1/places/{place['id']}",
        json={"is_polygon": True, "area": SQUARE, "x": None, "y": None},
    )

    assert response.status_code == 200, response.text
    expected = place | {"is_polygon": True, "area": SQUARE, "x": None, "y": None}
    assert response.json() == expected
    assert (await api.get(f"/api/v1/places/{place['id']}")).json() == expected


async def test_patch_turns_polygon_into_point(api) -> None:
    place = await _polygon(api)

    response = await api.patch(
        f"/api/v1/places/{place['id']}",
        json={"is_polygon": False, "area": None, "x": 3.0, "y": 4.0},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["is_polygon"], body["x"], body["y"], body["area"]) == (
        False,
        3.0,
        4.0,
        None,
    )


async def test_patch_replaces_area_of_polygon(api) -> None:
    place = await _polygon(api)
    triangle = SQUARE[:3]

    response = await api.patch(f"/api/v1/places/{place['id']}", json={"area": triangle})

    assert response.status_code == 200, response.text
    assert response.json()["area"] == triangle


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        # 저장된 값과 합쳐 판정한다. 반대쪽 값을 비우지 않으면 422다.
        ({"is_polygon": True, "area": SQUARE}, ["x", "y"]),
        ({"is_polygon": True, "x": None, "y": None}, ["area"]),
        ({"area": SQUARE}, ["area"]),
    ],
)
async def test_patch_point_into_mismatched_shape_is_422(api, body, fields) -> None:
    category = await seeded_category(api)
    place = await create_place(api, category["id"])

    response = await api.patch(f"/api/v1/places/{place['id']}", json=body)

    assert response.status_code == 422
    assert [row["field"] for row in response.json()["details"]] == fields
    assert (await api.get(f"/api/v1/places/{place['id']}")).json() == place


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"area": None}, ["area"]),
        ({"x": 1.0, "y": 2.0}, ["x", "y"]),
        ({"is_polygon": False}, ["x", "y", "area"]),
    ],
)
async def test_patch_polygon_into_mismatched_shape_is_422(api, body, fields) -> None:
    place = await _polygon(api)

    response = await api.patch(f"/api/v1/places/{place['id']}", json=body)

    assert response.status_code == 422
    assert [row["field"] for row in response.json()["details"]] == fields
    assert (await api.get(f"/api/v1/places/{place['id']}")).json() == place


async def test_patch_is_polygon_null_is_422(api) -> None:
    place = await _polygon(api)

    response = await api.patch(
        f"/api/v1/places/{place['id']}", json={"is_polygon": None}
    )

    assert response.status_code == 422


async def test_list_mixes_point_and_polygon_places(api) -> None:
    point = (await api.post("/api/v1/places", json={"x": 0.0, "y": 0.0})).json()
    polygon = await _polygon(api)

    items = (await api.get("/api/v1/places")).json()["items"]

    assert items == [point, polygon]
