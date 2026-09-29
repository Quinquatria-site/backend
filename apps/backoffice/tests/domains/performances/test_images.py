"""공연 이미지 연결·교체·해제 (명세 §4.6)."""

from quinquatria_persistence.enums import ImageStatus

from ._support import create, image_status, uploaded_image


async def test_create_attaches_the_image(api, database, object_store) -> None:
    key = await uploaded_image(database, object_store, "poster")

    created = await create(api, image_uri=key)

    assert created["image_uri"] == key
    assert await image_status(database, key) is ImageStatus.ATTACHED


async def test_patch_replaces_and_detaches_the_old_image(
    api, database, object_store
) -> None:
    old = await uploaded_image(database, object_store, "old")
    new = await uploaded_image(database, object_store, "new")
    created = await create(api, image_uri=old)

    response = await api.patch(
        f"/api/v1/performances/{created['id']}", json={"image_uri": new}
    )

    assert response.status_code == 200
    assert response.json()["image_uri"] == new
    assert await image_status(database, old) is ImageStatus.DETACHED
    assert await image_status(database, new) is ImageStatus.ATTACHED


async def test_patch_null_detaches_the_image(api, database, object_store) -> None:
    key = await uploaded_image(database, object_store, "poster")
    created = await create(api, image_uri=key)

    response = await api.patch(
        f"/api/v1/performances/{created['id']}", json={"image_uri": None}
    )

    assert response.status_code == 200
    assert response.json()["image_uri"] is None
    assert await image_status(database, key) is ImageStatus.DETACHED


async def test_patch_resending_the_current_key_is_a_no_op(
    api, database, object_store
) -> None:
    key = await uploaded_image(database, object_store, "poster")
    created = await create(api, image_uri=key)

    response = await api.patch(
        f"/api/v1/performances/{created['id']}", json={"image_uri": key}
    )

    assert response.status_code == 200
    assert response.json()["image_uri"] == key
    assert await image_status(database, key) is ImageStatus.ATTACHED


async def test_delete_detaches_the_image(api, database, object_store) -> None:
    key = await uploaded_image(database, object_store, "poster")
    created = await create(api, image_uri=key)

    response = await api.delete(f"/api/v1/performances/{created['id']}")

    assert response.status_code == 204
    assert await image_status(database, key) is ImageStatus.DETACHED


async def test_key_of_another_resource_type_is_invalid(api, object_store) -> None:
    response = await api.post(
        "/api/v1/performances",
        json={
            "type": "ARTIST",
            "date": "2026-10-06",
            "image_uri": "images/place/poster.webp",
            "translations": [{"language_code": "KO", "title": "공연"}],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"


async def test_key_used_by_another_performance_conflicts(
    api, database, object_store
) -> None:
    key = await uploaded_image(database, object_store, "poster")
    await create(api, "a", image_uri=key)
    other = await create(api, "b")

    response = await api.patch(
        f"/api/v1/performances/{other['id']}", json={"image_uri": key}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "IMAGE_ALREADY_ATTACHED"
