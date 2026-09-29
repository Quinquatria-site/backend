"""`PUT /performances/reorder` (명세 §5.6의 판정 표)."""

import pytest
from fastapi.routing import APIRoute

from backoffice.domains.performances.routes import router

from ._support import DAY_ONE, DAY_TWO, create, order_of


def test_reorder_is_registered_before_id_routes() -> None:
    paths = [route.path for route in router.routes if isinstance(route, APIRoute)]

    first_id_route = next(
        index for index, path in enumerate(paths) if "{performance_id}" in path
    )
    assert paths.index("/performances/reorder") < first_id_route


@pytest.fixture
async def day(api) -> dict[str, int]:
    """명세 표의 상태. `seq` 순서는 12, 30, 7, 5이고 44는 다른 일차다."""
    ids = {}
    for name in ("12", "30", "7", "5"):
        ids[name] = (await create(api, name))["id"]
    ids["44"] = (await create(api, "44", date=DAY_TWO))["id"]
    return ids


async def _reorder(api, payload):
    return await api.put("/api/v1/performances/reorder", json=payload)


async def test_reorder_assigns_seq_by_position(api, database, day) -> None:
    order = [day["5"], day["30"], day["7"], day["12"]]

    response = await _reorder(api, {"date": DAY_ONE, "order": order})

    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers
    assert await order_of(database, DAY_ONE) == [
        (performance_id, position) for position, performance_id in enumerate(order, 1)
    ]
    assert await order_of(database, DAY_TWO) == [(day["44"], 1)]


async def test_reorder_with_the_same_order_is_allowed(api, database, day) -> None:
    order = [day["12"], day["30"], day["7"], day["5"]]

    for _ in range(2):
        assert (
            await _reorder(api, {"date": DAY_ONE, "order": order})
        ).status_code == 204
    assert [pid for pid, _ in await order_of(database, DAY_ONE)] == order


@pytest.mark.parametrize(
    "names",
    [
        ["5", "30", "7"],
        ["5", "30", "7", "12", "99"],
        ["5", "5", "7", "12"],
        ["5", "30", "7", "44"],
    ],
    ids=["missing", "unknown", "duplicate", "other-date"],
)
async def test_reorder_rejects_a_different_set(api, database, day, names) -> None:
    order = [day.get(name, 99) for name in names]
    before = await order_of(database, DAY_ONE)

    response = await _reorder(api, {"date": DAY_ONE, "order": order})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert await order_of(database, DAY_ONE) == before


@pytest.mark.parametrize(
    "payload",
    [
        {"date": DAY_ONE, "order": []},
        {"date": "2026-10-06T00:00:00", "order": [1]},
        {"date": "20261006", "order": [1]},
        {"order": [1]},
        {"date": DAY_ONE},
        {"date": DAY_ONE, "order": ["1"]},
        {"date": DAY_ONE, "order": [0]},
        {"date": DAY_ONE, "order": [1], "seq": 1},
    ],
)
async def test_reorder_rejects_invalid_bodies(api, payload) -> None:
    response = await _reorder(api, payload)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_reorder_of_an_empty_date_is_rejected(api, day) -> None:
    response = await _reorder(api, {"date": "2026-10-08", "order": [day["44"]]})

    assert response.status_code == 422


async def test_reorder_keeps_the_live_flag(api, day) -> None:
    await api.put(f"/api/v1/performances/{day['7']}/live", json={"is_live": True})

    await _reorder(
        api, {"date": DAY_ONE, "order": [day["7"], day["5"], day["30"], day["12"]]}
    )

    live = (await api.get(f"/api/v1/performances/{day['7']}")).json()
    assert (live["seq"], live["is_live"]) == (1, True)
