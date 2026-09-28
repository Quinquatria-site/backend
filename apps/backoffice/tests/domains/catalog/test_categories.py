"""명세 §5.3 Category CRUD 계약."""

import pytest

from ._helpers import category_body, create_category


async def test_create_returns_201_with_all_translations(api) -> None:
    response = await api.post(
        "/api/v1/categories",
        json=category_body(
            translations=[
                {"language_code": "KO", "name": "주점"},
                {"language_code": "EN", "name": "Pub"},
            ]
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "id": body["id"],
        "code": "PUB",
        "category_icon_uri": None,
        "translations": [
            {
                "id": body["translations"][0]["id"],
                "category_id": body["id"],
                "language_code": "EN",
                "name": "Pub",
            },
            {
                "id": body["translations"][1]["id"],
                "category_id": body["id"],
                "language_code": "KO",
                "name": "주점",
            },
        ],
    }


async def test_get_returns_the_created_category(api) -> None:
    created = await create_category(api)

    response = await api.get(f"/api/v1/categories/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_get_rejects_query_parameters(api) -> None:
    created = await create_category(api)

    response = await api.get(
        f"/api/v1/categories/{created['id']}", params={"language_code": "KO"}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_get_missing_category_is_404(api) -> None:
    response = await api.get("/api/v1/categories/999")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_list_filters_by_code_in_id_order(api) -> None:
    first = await create_category(api, code="PUB")
    await create_category(api, code="BOOTH")
    third = await create_category(api, code="PUB")

    response = await api.get("/api/v1/categories", params={"code": "PUB"})

    assert response.status_code == 200
    assert response.json() == {
        "items": [first, third],
        "page": 1,
        "size": 20,
        "total": 2,
    }


async def test_list_paginates(api) -> None:
    created = [await create_category(api) for _ in range(3)]

    response = await api.get("/api/v1/categories", params={"page": 2, "size": 2})

    assert response.json() == {
        "items": [created[2]],
        "page": 2,
        "size": 2,
        "total": 3,
    }


async def test_list_rejects_unknown_code(api) -> None:
    response = await api.get("/api/v1/categories", params={"code": "pub"})

    assert response.status_code == 422


async def test_patch_upserts_translations_keeping_ids(api) -> None:
    created = await create_category(
        api,
        translations=[
            {"language_code": "KO", "name": "주점"},
            {"language_code": "EN", "name": "Pub"},
        ],
    )
    en_id, ko_id = (row["id"] for row in created["translations"])

    response = await api.patch(
        f"/api/v1/categories/{created['id']}",
        json={
            "code": "BOOTH",
            "translations": [
                {"language_code": "KO", "name": "부스"},
                {"language_code": "CHN", "name": "摊位"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "BOOTH"
    assert [(row["language_code"], row["name"]) for row in body["translations"]] == [
        ("CHN", "摊位"),
        ("EN", "Pub"),
        ("KO", "부스"),
    ]
    assert body["translations"][1]["id"] == en_id
    assert body["translations"][2]["id"] == ko_id
    assert (await api.get(f"/api/v1/categories/{created['id']}")).json() == body


async def test_patch_without_fields_is_422(api) -> None:
    created = await create_category(api)

    response = await api.patch(f"/api/v1/categories/{created['id']}", json={})

    assert response.status_code == 422


async def test_patch_missing_category_is_404(api) -> None:
    response = await api.patch("/api/v1/categories/999", json={"code": "PUB"})

    assert response.status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"code": "pub"},
        {"id": 1},
        {"translations": []},
        {"translations": [{"language_code": "EN", "name": "Pub"}]},
        {
            "translations": [
                {"language_code": "KO", "name": "주점"},
                {"language_code": "KO", "name": "술집"},
            ]
        },
        {"translations": [{"language_code": "KO", "name": "주점", "id": 1}]},
    ],
)
async def test_invalid_create_body_is_422(api, overrides) -> None:
    response = await api.post("/api/v1/categories", json=category_body(**overrides))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_requests_without_token_are_rejected(api) -> None:
    response = await api.get("/api/v1/categories", headers={"Authorization": ""})

    assert response.status_code == 401
