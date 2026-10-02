"""명세 §5.3 Category 계약. 카테고리는 migration이 넣는 고정 목록이다."""

import pytest

from ._helpers import SEEDED_CATEGORIES, seeded_category


def _seeded(code: str) -> dict:
    """번역 id를 뺀 시드 카테고리. 번역은 `CHN`, `EN`, `KO` 순이다."""
    category_id, names = SEEDED_CATEGORIES[code]
    return {
        "id": category_id,
        "code": code,
        "category_icon_uri": None,
        "translations": [
            {
                "category_id": category_id,
                "language_code": language,
                "name": names[language],
            }
            for language in ("CHN", "EN", "KO")
        ],
    }


def _without_translation_ids(body: dict) -> dict:
    return body | {
        "translations": [
            {key: value for key, value in row.items() if key != "id"}
            for row in body["translations"]
        ]
    }


async def test_list_returns_the_seeded_categories_in_id_order(api) -> None:
    response = await api.get("/api/v1/categories")

    assert response.status_code == 200
    body = response.json()
    assert [_without_translation_ids(item) for item in body["items"]] == [
        _seeded(code) for code in SEEDED_CATEGORIES
    ]
    assert (body["page"], body["size"], body["total"]) == (1, 20, 6)


async def test_list_filters_by_code(api) -> None:
    response = await api.get("/api/v1/categories", params={"code": "TRASHCAN"})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [5]


async def test_list_paginates(api) -> None:
    response = await api.get("/api/v1/categories", params={"page": 2, "size": 4})

    body = response.json()
    assert [item["code"] for item in body["items"]] == ["TRASHCAN", "PHOTOBOOTH"]
    assert body["total"] == 6


@pytest.mark.parametrize("code", ["pub", "BRACELET"])
async def test_list_rejects_unknown_code(api, code) -> None:
    response = await api.get("/api/v1/categories", params={"code": code})

    assert response.status_code == 422


async def test_get_returns_the_seeded_category(api) -> None:
    response = await api.get("/api/v1/categories/6")

    assert response.status_code == 200
    assert _without_translation_ids(response.json()) == _seeded("PHOTOBOOTH")


async def test_get_rejects_query_parameters(api) -> None:
    response = await api.get("/api/v1/categories/1", params={"language_code": "KO"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_get_missing_category_is_404(api) -> None:
    response = await api.get("/api/v1/categories/999")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_patch_upserts_translations_keeping_ids(api) -> None:
    before = await seeded_category(api)
    chn_id, en_id, ko_id = (row["id"] for row in before["translations"])

    response = await api.patch(
        "/api/v1/categories/1",
        json={
            "translations": [
                {"language_code": "KO", "name": "술집"},
                {"language_code": "EN", "name": "Bar"},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "PUB"
    assert [(row["id"], row["name"]) for row in body["translations"]] == [
        (chn_id, "酒馆"),
        (en_id, "Bar"),
        (ko_id, "술집"),
    ]
    assert (await api.get("/api/v1/categories/1")).json() == body


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"code": "BOOTH"},
        {"code": "PUB"},
        {"id": 2},
        {"translations": []},
        {
            "translations": [
                {"language_code": "KO", "name": "주점"},
                {"language_code": "KO", "name": "술집"},
            ]
        },
        {"translations": [{"language_code": "KO", "name": "주점", "id": 1}]},
    ],
)
async def test_invalid_patch_body_is_422(api, body) -> None:
    response = await api.patch("/api/v1/categories/1", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert _without_translation_ids(
        (await api.get("/api/v1/categories/1")).json()
    ) == _seeded("PUB")


async def test_patch_missing_category_is_404(api) -> None:
    response = await api.patch(
        "/api/v1/categories/999", json={"category_icon_uri": None}
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/api/v1/categories"), ("DELETE", "/api/v1/categories/1")],
)
async def test_create_and_delete_are_not_offered(api, method, path) -> None:
    """고정 목록이라 생성·삭제 경로가 없다 (명세 §5.1)."""
    response = await api.request(
        method,
        path,
        json={"code": "PUB", "translations": [{"language_code": "KO", "name": "주점"}]},
    )

    assert response.status_code == 405
    assert response.json()["code"] == "INVALID_REQUEST"
    assert (await api.get("/api/v1/categories")).json()["total"] == 6


async def test_requests_without_token_are_rejected(api) -> None:
    response = await api.get("/api/v1/categories", headers={"Authorization": ""})

    assert response.status_code == 401
