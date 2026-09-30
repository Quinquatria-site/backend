"""공연 생성과 단건 조회 (명세 §5.1, §5.2, §5.6)."""

import pytest

from ._support import DAY_ONE, DAY_TWO, body, create, order_of


async def test_create_returns_the_full_resource(api) -> None:
    response = await api.post(
        "/api/v1/performances",
        json=body(
            translations=[
                {"language_code": "KO", "title": "초청 공연", "description": "설명"},
                {"language_code": "EN", "title": "Guest"},
            ]
        ),
    )

    assert response.status_code == 201
    created = response.json()
    assert created == {
        "id": created["id"],
        "type": "ARTIST",
        "image_uri": None,
        "date": DAY_ONE,
        "seq": 1,
        "is_live": False,
        "translations": [
            {
                "id": created["translations"][0]["id"],
                "performance_id": created["id"],
                "language_code": "EN",
                "title": "Guest",
                "description": "",
            },
            {
                "id": created["translations"][1]["id"],
                "performance_id": created["id"],
                "language_code": "KO",
                "title": "초청 공연",
                "description": "설명",
            },
        ],
    }


async def test_get_returns_the_same_resource(api) -> None:
    created = await create(api)

    response = await api.get(f"/api/v1/performances/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_get_rejects_query_parameters(api) -> None:
    created = await create(api)

    response = await api.get(
        f"/api/v1/performances/{created['id']}", params={"language_code": "KO"}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("performance_id", [999, 2_147_483_648])
async def test_get_unknown_id_is_not_found(api, performance_id) -> None:
    response = await api.get(f"/api/v1/performances/{performance_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_new_performances_go_to_the_end_of_their_date(api, database) -> None:
    first = await create(api, "하나")
    other_day = await create(api, "다른 날", date=DAY_TWO)
    second = await create(api, "둘")

    assert (first["seq"], other_day["seq"], second["seq"]) == (1, 1, 2)
    assert await order_of(database, DAY_ONE) == [(first["id"], 1), (second["id"], 2)]


@pytest.mark.parametrize("field", ["seq", "is_live", "id"])
async def test_create_rejects_server_controlled_fields(api, field) -> None:
    value = False if field == "is_live" else 1

    response = await api.post("/api/v1/performances", json=body(**{field: value}))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-06T00:00:00",
        "2026-10-06T00:00:00+09:00",
        "20261006",
        "2026-1-6",
        1790000000,
        None,
        "2026-02-30",
    ],
)
async def test_create_requires_an_iso_local_date(api, value) -> None:
    response = await api.post("/api/v1/performances", json=body(date=value))

    assert response.status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "artist"},
        {"type": "UNKNOWN"},
        {"translations": [{"language_code": "EN", "title": "Guest"}]},
        {"translations": [{"language_code": "KO"}]},
        {
            "translations": [
                {"language_code": "KO", "title": "a"},
                {"language_code": "KO", "title": "b"},
            ]
        },
        {"translations": [{"language_code": "KO", "title": "a", "id": 1}]},
    ],
)
async def test_create_rejects_invalid_bodies(api, changes) -> None:
    response = await api.post("/api/v1/performances", json=body() | changes)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_create_requires_type_and_date(api) -> None:
    for missing in ("type", "date", "translations"):
        payload = body()
        del payload[missing]
        response = await api.post("/api/v1/performances", json=payload)
        assert response.status_code == 422, missing
