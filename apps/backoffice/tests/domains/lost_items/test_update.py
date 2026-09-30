"""`PATCH /api/v1/lost-items/{id}` (명세 §5.2, §4.6)."""

import pytest

from quinquatria_persistence.enums import ImageStatus

from ._support import URL, body, image_status, ko, seed_image


async def _create(api, **overrides) -> dict:
    response = await api.post(URL, json=body(**overrides))
    assert response.status_code == 201
    return response.json()


def _by_language(resource: dict) -> dict[str, dict]:
    return {t["language_code"]: t for t in resource["translations"]}


async def test_patch_updates_only_sent_fields(api) -> None:
    created = await _create(api)

    response = await api.patch(f"{URL}/{created['id']}", json={"is_returned": True})

    assert response.status_code == 200
    assert response.json() == {**created, "is_returned": True}
    assert (await api.get(f"{URL}/{created['id']}")).json() == response.json()


async def test_patch_upserts_translations_and_keeps_ids(api) -> None:
    created = await _create(
        api,
        translations=[
            ko(title="지갑", description="검정", found_location="본관"),
            {"language_code": "CHN", "title": "钱包"},
        ],
    )
    before = _by_language(created)

    response = await api.patch(
        f"{URL}/{created['id']}",
        json={
            "translations": [
                {"language_code": "KO", "title": "갈색 지갑"},
                {"language_code": "EN", "title": "Wallet", "found_location": "Hall"},
            ]
        },
    )

    assert response.status_code == 200
    updated = response.json()
    after = _by_language(updated)
    assert [t["language_code"] for t in updated["translations"]] == ["CHN", "EN", "KO"]
    assert after["CHN"] == before["CHN"]
    assert after["KO"] == {
        **before["KO"],
        "title": "갈색 지갑",
        "description": "",
        "found_location": "",
    }
    assert after["EN"]["lost_item_id"] == created["id"]
    assert (after["EN"]["description"], after["EN"]["found_location"]) == ("", "Hall")
    assert updated["is_returned"] is created["is_returned"]
    assert (await api.get(f"{URL}/{created['id']}")).json() == updated


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"translations": []},
        {"is_returned": None},
        {"is_returned": "true"},
        {"is_returned": 0},
        {"translations": None},
        {"translations": [ko(), ko()]},
        {"translations": [{"language_code": "EN"}]},
        {"created_at": "2026-10-06T18:00:00+09:00"},
        {"id": 3},
    ],
    ids=[
        "empty",
        "empty-translations",
        "null-is-returned",
        "string-is-returned",
        "int-is-returned",
        "null-translations",
        "duplicate-language",
        "missing-title",
        "created-at",
        "id",
    ],
)
async def test_patch_rejects_invalid_body(api, payload) -> None:
    created = await _create(api)

    response = await api.patch(f"{URL}/{created['id']}", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert (await api.get(f"{URL}/{created['id']}")).json() == created


async def test_patch_missing_is_not_found(api) -> None:
    response = await api.patch(f"{URL}/999", json={"is_returned": True})

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_patch_attaches_image_to_item_without_one(
    api, database, object_store
) -> None:
    created = await _create(api)
    key = await seed_image(database, object_store, "later")

    response = await api.patch(f"{URL}/{created['id']}", json={"image_url": key})

    assert response.status_code == 200
    assert response.json()["image_url"] == key
    assert await image_status(database, key) is ImageStatus.ATTACHED


async def test_patch_replaces_image_and_detaches_previous(
    api, database, object_store
) -> None:
    old = await seed_image(database, object_store, "old")
    new = await seed_image(database, object_store, "new")
    created = await _create(api, image_url=old)

    response = await api.patch(f"{URL}/{created['id']}", json={"image_url": new})

    assert response.json()["image_url"] == new
    assert await image_status(database, old) is ImageStatus.DETACHED
    assert await image_status(database, new) is ImageStatus.ATTACHED


async def test_patch_resending_current_image_is_noop(
    api, database, object_store
) -> None:
    key = await seed_image(database, object_store, "same")
    created = await _create(api, image_url=key)

    response = await api.patch(
        f"{URL}/{created['id']}", json={"image_url": key, "is_returned": True}
    )

    assert response.status_code == 200
    assert response.json()["image_url"] == key
    assert await image_status(database, key) is ImageStatus.ATTACHED


async def test_patch_null_detaches_image(api, database, object_store) -> None:
    key = await seed_image(database, object_store, "gone")
    created = await _create(api, image_url=key)

    response = await api.patch(f"{URL}/{created['id']}", json={"image_url": None})

    assert response.status_code == 200
    assert response.json()["image_url"] is None
    assert await image_status(database, key) is ImageStatus.DETACHED


async def test_patch_key_of_another_item_is_conflict(
    api, database, object_store
) -> None:
    key = await seed_image(database, object_store, "other")
    await _create(api, image_url=key)
    target = await _create(api)

    response = await api.patch(f"{URL}/{target['id']}", json={"image_url": key})

    assert response.status_code == 409
    assert response.json()["code"] == "IMAGE_ALREADY_ATTACHED"


async def test_patch_detached_key_is_invalid(api, database, object_store) -> None:
    key = await seed_image(database, object_store, "detached")
    created = await _create(api, image_url=key)
    await api.patch(f"{URL}/{created['id']}", json={"image_url": None})

    response = await api.patch(f"{URL}/{created['id']}", json={"image_url": key})

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"


async def test_invalid_image_rolls_back_whole_patch(
    api, database, object_store
) -> None:
    old = await seed_image(database, object_store, "kept")
    # prefix는 맞아야 원장 조회 전 autoflush로 변경이 DB에 먼저 나간다.
    wrong = await seed_image(database, object_store, "wrong", content=b"not-webp")
    created = await _create(api, image_url=old)

    response = await api.patch(
        f"{URL}/{created['id']}",
        json={
            "is_returned": True,
            "image_url": wrong,
            "translations": [
                {"language_code": "KO", "title": "변경"},
                {"language_code": "EN", "title": "Changed"},
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"
    assert (await api.get(f"{URL}/{created['id']}")).json() == created
    assert await image_status(database, old) is ImageStatus.ATTACHED
