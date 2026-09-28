"""명세 §5.4 Place CRUD 계약."""

import pytest

from ._helpers import create_category, create_place, place_body


async def test_create_returns_201_with_all_fields(api) -> None:
    category = await create_category(api)

    response = await api.post(
        "/api/v1/places",
        json=place_body(
            category["id"],
            category_sequence=3,
            translations=[
                {
                    "language_code": "KO",
                    "name": "주점",
                    "host_college": "통번역대학",
                    "description": "음식",
                },
                {"language_code": "EN", "name": "Pub", "host_college": "CIT"},
            ],
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "id": body["id"],
        "category_id": category["id"],
        "category_sequence": 3,
        "x": 127.42,
        "y": 36.18,
        "start_hour": "2026-10-06T01:00:00Z",
        "end_hour": "2026-10-06T13:00:00Z",
        "place_image_uri": None,
        "translations": [
            {
                "id": body["translations"][0]["id"],
                "place_id": body["id"],
                "language_code": "EN",
                "name": "Pub",
                "host_college": "CIT",
                "description": "",
            },
            {
                "id": body["translations"][1]["id"],
                "place_id": body["id"],
                "language_code": "KO",
                "name": "주점",
                "host_college": "통번역대학",
                "description": "음식",
            },
        ],
    }
    assert (await api.get(f"/api/v1/places/{body['id']}")).json() == body


async def test_create_with_missing_category_is_404(api) -> None:
    response = await api.post("/api/v1/places", json=place_body(999))

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_equal_hours_are_allowed(api) -> None:
    category = await create_category(api)

    response = await api.post(
        "/api/v1/places",
        json=place_body(
            category["id"],
            start_hour="2026-10-06T10:00:00+09:00",
            end_hour="2026-10-06T10:00:00+09:00",
        ),
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    "overrides",
    [
        {"end_hour": "2026-10-06T09:59:59+09:00"},
        {"category_sequence": 0},
        {"category_sequence": "1"},
        {"category_sequence": True},
        {"x": "1.5"},
        {"start_hour": "2026-10-06T10:00:00"},
        {"id": 1},
        {"place_image_uri": []},
        {"place_image_uri": [None]},
        {"place_image_uri": [["images/place/a.webp"]]},
    ],
)
async def test_invalid_create_body_is_422(api, overrides) -> None:
    category = await create_category(api)

    response = await api.post(
        "/api/v1/places", json=place_body(category["id"], **overrides)
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_get_rejects_query_parameters(api) -> None:
    category = await create_category(api)
    place = await create_place(api, category["id"])

    response = await api.get(f"/api/v1/places/{place['id']}", params={"page": 1})

    assert response.status_code == 422


async def test_list_sorts_by_category_then_sequence(api) -> None:
    first = await create_category(api)
    second = await create_category(api)
    b = await create_place(api, second["id"], category_sequence=1)
    a2 = await create_place(api, first["id"], category_sequence=2)
    a1 = await create_place(api, first["id"], category_sequence=1)

    response = await api.get("/api/v1/places")

    assert [item["id"] for item in response.json()["items"]] == [
        a1["id"],
        a2["id"],
        b["id"],
    ]


async def test_sequence_taken_in_the_category_is_422(api) -> None:
    category = await create_category(api)
    await create_place(api, category["id"], category_sequence=5)

    response = await api.post(
        "/api/v1/places", json=place_body(category["id"], category_sequence=5)
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert [row["field"] for row in response.json()["details"]] == ["category_sequence"]
    listed = await api.get("/api/v1/places", params={"category_id": category["id"]})
    assert listed.json()["total"] == 1


async def test_same_sequence_in_another_category_is_allowed(api) -> None:
    first = await create_category(api)
    second = await create_category(api)
    await create_place(api, first["id"], category_sequence=5)

    response = await api.post(
        "/api/v1/places", json=place_body(second["id"], category_sequence=5)
    )

    assert response.status_code == 201


async def test_list_filters_by_category(api) -> None:
    first = await create_category(api)
    second = await create_category(api)
    await create_place(api, first["id"])
    wanted = await create_place(api, second["id"])

    response = await api.get("/api/v1/places", params={"category_id": second["id"]})

    assert response.json() == {"items": [wanted], "page": 1, "size": 20, "total": 1}


async def test_list_with_out_of_range_category_is_empty(api) -> None:
    category = await create_category(api)
    await create_place(api, category["id"])

    response = await api.get("/api/v1/places", params={"category_id": 2_147_483_648})

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "size": 20, "total": 0}


async def test_patch_updates_only_sent_fields(api) -> None:
    category = await create_category(api)
    other = await create_category(api)
    place = await create_place(api, category["id"])

    response = await api.patch(
        f"/api/v1/places/{place['id']}",
        json={
            "category_id": other["id"],
            "x": 1.0,
            "translations": [
                {"language_code": "EN", "name": "Pub", "host_college": "CIT"}
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["category_id"] == other["id"]
    assert body["x"] == 1.0
    assert body["y"] == place["y"]
    assert [row["language_code"] for row in body["translations"]] == ["EN", "KO"]
    assert body["translations"][1] == place["translations"][0]


async def test_patch_to_missing_category_is_404(api) -> None:
    category = await create_category(api)
    place = await create_place(api, category["id"])

    response = await api.patch(
        f"/api/v1/places/{place['id']}", json={"category_id": 999}
    )

    assert response.status_code == 404


async def test_patch_checks_hours_against_stored_values(api) -> None:
    """한쪽만 보내도 기존 값과 합친 결과로 판정한다."""
    category = await create_category(api)
    place = await create_place(api, category["id"])

    response = await api.patch(
        f"/api/v1/places/{place['id']}",
        json={"end_hour": "2026-10-06T09:00:00+09:00"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert (await api.get(f"/api/v1/places/{place['id']}")).json() == place


async def test_patch_may_move_both_hours_together(api) -> None:
    category = await create_category(api)
    place = await create_place(api, category["id"])

    response = await api.patch(
        f"/api/v1/places/{place['id']}",
        json={
            "start_hour": "2026-10-07T00:00:00+09:00",
            "end_hour": "2026-10-07T00:00:00+09:00",
        },
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"x": None},
        {"category_sequence": 0},
        {"place_image_uri": []},
    ],
)
async def test_invalid_patch_body_is_422(api, body) -> None:
    category = await create_category(api)
    place = await create_place(api, category["id"])

    response = await api.patch(f"/api/v1/places/{place['id']}", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("moves", ["sequence", "category"])
async def test_patch_onto_a_taken_sequence_is_422(api, moves) -> None:
    """번호만 바꾸든 카테고리만 옮기든 반영 후의 쌍으로 판정한다."""
    category = await create_category(api)
    other = await create_category(api)
    await create_place(api, category["id"], category_sequence=5)
    await create_place(api, other["id"], category_sequence=7)
    if moves == "sequence":
        place = await create_place(api, category["id"], category_sequence=6)
        body = {"category_sequence": 5}
    else:
        place = await create_place(api, other["id"], category_sequence=5)
        body = {"category_id": category["id"]}

    response = await api.patch(f"/api/v1/places/{place['id']}", json=body)

    assert response.status_code == 422
    assert response.json()["details"][0]["field"] == "category_sequence"
    assert (await api.get(f"/api/v1/places/{place['id']}")).json() == place


async def test_patch_resending_its_own_sequence_is_allowed(api) -> None:
    category = await create_category(api)
    place = await create_place(api, category["id"], category_sequence=5)

    response = await api.patch(
        f"/api/v1/places/{place['id']}",
        json={"category_id": category["id"], "category_sequence": 5},
    )

    assert response.status_code == 200
    assert response.json() == place


async def test_patch_missing_place_is_404(api) -> None:
    response = await api.patch("/api/v1/places/999", json={"x": 1.0})

    assert response.status_code == 404
