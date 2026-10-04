"""공지 이미지 배열의 순서 보존, 교체와 해제 (명세 §4.6, §5.7)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from quinquatria_persistence.enums import ImageStatus
from quinquatria_persistence.models import Image

from ..._images import FakeObjectStore, put_object
from .test_create import KO

URL = "/api/v1/notices"
WEBP = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 64


async def _upload(
    api: AsyncClient, store: FakeObjectStore, resource_type: str = "NOTICE_IMAGE"
) -> str:
    """발급 API로 key를 받고 S3 업로드까지 끝낸 것처럼 객체를 둔다."""
    response = await api.post(
        "/api/v1/uploads/images/presigned-url",
        json={
            "resource_type": resource_type,
            "content_type": "image/webp",
            "size": len(WEBP),
        },
    )
    assert response.status_code == 200, response.text
    key = response.json()["object_key"]
    put_object(store, key, body=WEBP, content_type="image/webp")
    return key


async def _keys(api: AsyncClient, store: FakeObjectStore, count: int) -> list[str]:
    return [await _upload(api, store) for _ in range(count)]


async def _create(api: AsyncClient, **fields) -> dict:
    response = await api.post(
        URL, json={"type": "GENERAL", "translations": [KO], **fields}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _status(database, key: str) -> ImageStatus:
    async with database.session() as session:
        return await session.scalar(select(Image.status).where(Image.s3_key == key))


async def test_notice_without_images_is_null(api: AsyncClient) -> None:
    created = await _create(api)

    assert created["notice_image_uri"] is None
    assert (await api.get(f"{URL}/{created['id']}")).json() == created


async def test_create_preserves_image_order(
    api: AsyncClient, database, object_store
) -> None:
    keys = await _keys(api, object_store, 3)
    ordered = [keys[2], keys[0], keys[1]]

    created = await _create(api, notice_image_uri=ordered)

    assert created["notice_image_uri"] == ordered
    assert (await api.get(f"{URL}/{created['id']}")).json() == created
    assert (await api.get(URL)).json()["items"] == [created]
    for key in keys:
        assert await _status(database, key) is ImageStatus.ATTACHED


@pytest.mark.parametrize(
    "value",
    [
        pytest.param([], id="empty"),
        pytest.param([None], id="null-element"),
        pytest.param([["images/notice/a.webp"]], id="nested"),
        pytest.param("images/notice/a.webp", id="bare-string"),
    ],
)
async def test_malformed_array_is_validation_error(api: AsyncClient, value) -> None:
    response = await api.post(
        URL, json={"type": "GENERAL", "translations": [KO], "notice_image_uri": value}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_duplicate_keys_are_invalid_image(api: AsyncClient, object_store) -> None:
    [key] = await _keys(api, object_store, 1)

    response = await api.post(
        URL,
        json={"type": "GENERAL", "translations": [KO], "notice_image_uri": [key, key]},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"


async def test_key_for_another_resource_is_invalid_image(
    api: AsyncClient, object_store
) -> None:
    key = await _upload(api, object_store, "PLACE_IMAGE")

    response = await api.post(
        URL, json={"type": "GENERAL", "translations": [KO], "notice_image_uri": [key]}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"


async def test_key_attached_to_another_notice_is_conflict(
    api: AsyncClient, object_store
) -> None:
    [key] = await _keys(api, object_store, 1)
    await _create(api, notice_image_uri=[key])

    response = await api.post(
        URL, json={"type": "GENERAL", "translations": [KO], "notice_image_uri": [key]}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "IMAGE_ALREADY_ATTACHED"


async def test_patch_reorders_replaces_and_detaches(
    api: AsyncClient, database, object_store
) -> None:
    a, b, c, d = await _keys(api, object_store, 4)
    created = await _create(api, notice_image_uri=[a, b, c])

    response = await api.patch(
        f"{URL}/{created['id']}", json={"notice_image_uri": [c, d, a]}
    )

    assert response.status_code == 200
    assert response.json()["notice_image_uri"] == [c, d, a]
    got = await api.get(f"{URL}/{created['id']}")
    assert got.json()["notice_image_uri"] == [c, d, a]
    assert await _status(database, b) is ImageStatus.DETACHED
    assert await _status(database, d) is ImageStatus.ATTACHED


async def test_patch_without_images_keeps_them(
    api: AsyncClient, database, object_store
) -> None:
    a, b = await _keys(api, object_store, 2)
    created = await _create(api, notice_image_uri=[a, b])

    response = await api.patch(f"{URL}/{created['id']}", json={"type": "PERMANENT"})

    assert response.json()["notice_image_uri"] == [a, b]
    assert await _status(database, a) is ImageStatus.ATTACHED


async def test_patch_null_detaches_every_image(
    api: AsyncClient, database, object_store
) -> None:
    a, b = await _keys(api, object_store, 2)
    created = await _create(api, notice_image_uri=[a, b])

    response = await api.patch(
        f"{URL}/{created['id']}", json={"notice_image_uri": None}
    )

    assert response.json()["notice_image_uri"] is None
    assert await _status(database, a) is ImageStatus.DETACHED
    assert await _status(database, b) is ImageStatus.DETACHED


async def test_failed_image_rolls_back_fields_and_translations(
    api: AsyncClient, database, object_store
) -> None:
    [a] = await _keys(api, object_store, 1)
    created = await _create(api, notice_image_uri=[a])

    response = await api.patch(
        f"{URL}/{created['id']}",
        json={
            "type": "PERMANENT",
            "notice_image_uri": ["images/notice/missing.webp"],
            "translations": [{**KO, "title": "바뀜"}],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"
    assert (await api.get(f"{URL}/{created['id']}")).json() == created
    assert await _status(database, a) is ImageStatus.ATTACHED


async def test_delete_detaches_every_image(
    api: AsyncClient, database, object_store
) -> None:
    a, b = await _keys(api, object_store, 2)
    created = await _create(api, notice_image_uri=[a, b])

    response = await api.delete(f"{URL}/{created['id']}")

    assert response.status_code == 204
    assert await _status(database, a) is ImageStatus.DETACHED
    assert await _status(database, b) is ImageStatus.DETACHED
