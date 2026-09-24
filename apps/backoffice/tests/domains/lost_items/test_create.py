"""`POST /api/v1/lost-items` (명세 §5.2, §5.8)."""

from datetime import datetime

import pytest

from quinquatria_persistence.enums import ImageResourceType, ImageStatus

from ._support import URL, body, image_status, ko, seed_image


async def test_create_returns_created_resource(api) -> None:
    response = await api.post(
        URL,
        json=body(
            is_returned=True,
            translations=[
                ko(title="지갑", description="검정 가죽", found_location="본관"),
                {"language_code": "EN", "title": "Wallet"},
            ],
        ),
    )

    assert response.status_code == 201
    created = response.json()
    assert isinstance(created["id"], int)
    assert created["image_url"] is None
    assert created["is_returned"] is True
    assert datetime.fromisoformat(created["created_at"]).utcoffset() is not None
    assert [
        {k: v for k, v in t.items() if k != "id"} for t in created["translations"]
    ] == [
        {
            "lost_item_id": created["id"],
            "language_code": "EN",
            "title": "Wallet",
            "description": "",
            "found_location": "",
        },
        {
            "lost_item_id": created["id"],
            "language_code": "KO",
            "title": "지갑",
            "description": "검정 가죽",
            "found_location": "본관",
        },
    ]


async def test_created_resource_is_persisted(api) -> None:
    created = (await api.post(URL, json=body())).json()

    fetched = await api.get(f"{URL}/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.json() == created


@pytest.mark.parametrize("value", ["true", 1, None], ids=["string", "int", "null"])
async def test_is_returned_must_be_json_boolean(api, value) -> None:
    response = await api.post(URL, json=body(is_returned=value))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "payload",
    [
        {"translations": [ko()]},
        {"is_returned": False},
        body(translations=[]),
        body(translations=[{"language_code": "EN", "title": "Wallet"}]),
        body(translations=[ko(), ko()]),
        body(translations=[{"language_code": "KO"}]),
        body(translations=[ko(description=None)]),
        body(translations=[{"language_code": "ko", "title": "지갑"}]),
        body(created_at="2026-10-06T18:00:00+09:00"),
        body(id=1),
        body(translations=[{**ko(), "id": 1}]),
        body(translations=[{**ko(), "lost_item_id": 1}]),
    ],
    ids=[
        "missing-is-returned",
        "missing-translations",
        "empty-translations",
        "no-ko",
        "duplicate-ko",
        "missing-title",
        "null-description",
        "lowercase-language",
        "created-at",
        "id",
        "translation-id",
        "translation-fk",
    ],
)
async def test_invalid_body_is_rejected(api, payload) -> None:
    response = await api.post(URL, json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_create_attaches_image(api, database, object_store) -> None:
    key = await seed_image(database, object_store, "wallet")

    response = await api.post(URL, json=body(image_url=key))

    assert response.status_code == 201
    assert response.json()["image_url"] == key
    assert await image_status(database, key) is ImageStatus.ATTACHED


async def test_create_with_null_image(api) -> None:
    response = await api.post(URL, json=body(image_url=None))

    assert response.status_code == 201
    assert response.json()["image_url"] is None


async def test_create_with_attached_key_is_conflict(
    api, database, object_store
) -> None:
    key = await seed_image(database, object_store, "taken")
    await api.post(URL, json=body(image_url=key))

    response = await api.post(URL, json=body(image_url=key))

    assert response.status_code == 409
    assert response.json()["code"] == "IMAGE_ALREADY_ATTACHED"


async def test_create_with_invalid_image_creates_nothing(
    api, database, object_store
) -> None:
    place_key = await seed_image(
        database, object_store, "place", resource_type=ImageResourceType.PLACE_IMAGE
    )

    response = await api.post(URL, json=body(image_url=place_key))

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"
    assert (await api.get(URL)).json()["total"] == 0


async def test_create_rejects_image_with_wrong_signature(
    api, database, object_store
) -> None:
    key = await seed_image(database, object_store, "fake", content=b"not-an-image")

    response = await api.post(URL, json=body(image_url=key))

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"
    assert await image_status(database, key) is ImageStatus.UPLOADING


async def test_create_rejects_missing_object(api) -> None:
    response = await api.post(URL, json=body(image_url="images/lost-item/missing.webp"))

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"
