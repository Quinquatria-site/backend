"""공지 언어별 이미지 배열의 순서 보존, 교체와 해제 (명세 §4.6, §5.7)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from quinquatria_persistence.enums import ImageStatus
from quinquatria_persistence.models import Image

from ..._images import FakeObjectStore, put_object
from .test_create import EN, KO

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


def _with(translation: dict, keys) -> dict:
    return {**translation, "notice_image_uri": keys}


def _images(notice: dict) -> dict[str, list[str] | None]:
    return {t["language_code"]: t["notice_image_uri"] for t in notice["translations"]}


async def _create(api: AsyncClient, *translations: dict) -> dict:
    response = await api.post(
        URL, json={"type": "GENERAL", "translations": list(translations) or [KO]}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _status(database, key: str) -> ImageStatus:
    async with database.session() as session:
        return await session.scalar(select(Image.status).where(Image.s3_key == key))


async def test_notice_without_images_is_null_in_every_language(
    api: AsyncClient,
) -> None:
    created = await _create(api, KO, EN)

    assert _images(created) == {"EN": None, "KO": None}
    assert "notice_image_uri" not in created
    assert (await api.get(f"{URL}/{created['id']}")).json() == created


async def test_each_language_keeps_its_own_images_in_order(
    api: AsyncClient, database, object_store
) -> None:
    keys = await _keys(api, object_store, 3)
    ko_keys, en_keys = [keys[1], keys[0]], [keys[2]]

    created = await _create(api, _with(KO, ko_keys), _with(EN, en_keys))

    assert _images(created) == {"EN": en_keys, "KO": ko_keys}
    assert (await api.get(f"{URL}/{created['id']}")).json() == created
    assert (await api.get(URL)).json()["items"] == [created]
    for key in keys:
        assert await _status(database, key) is ImageStatus.ATTACHED


async def test_notice_level_image_field_is_gone(api: AsyncClient) -> None:
    """이미지는 번역 안에만 둔다. 공지 단위 필드는 extra 필드로 422다."""
    response = await api.post(
        URL, json={"type": "GENERAL", "translations": [KO], "notice_image_uri": None}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


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
        URL, json={"type": "GENERAL", "translations": [_with(KO, value)]}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_duplicate_keys_in_one_language_are_invalid_image(
    api: AsyncClient, object_store
) -> None:
    [key] = await _keys(api, object_store, 1)

    response = await api.post(
        URL, json={"type": "GENERAL", "translations": [_with(KO, [key, key])]}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"


async def test_one_key_in_two_languages_is_invalid_image(
    api: AsyncClient, database, object_store
) -> None:
    """같은 그림도 언어마다 따로 업로드한다."""
    [key] = await _keys(api, object_store, 1)

    response = await api.post(
        URL,
        json={"type": "GENERAL", "translations": [_with(KO, [key]), _with(EN, [key])]},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"
    assert await _status(database, key) is not ImageStatus.ATTACHED


async def test_key_for_another_resource_is_invalid_image(
    api: AsyncClient, object_store
) -> None:
    key = await _upload(api, object_store, "PLACE_IMAGE")

    response = await api.post(
        URL, json={"type": "GENERAL", "translations": [_with(KO, [key])]}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"


async def test_key_attached_to_another_notice_is_conflict(
    api: AsyncClient, object_store
) -> None:
    [key] = await _keys(api, object_store, 1)
    await _create(api, _with(KO, [key]))

    response = await api.post(
        URL, json={"type": "GENERAL", "translations": [_with(KO, [key])]}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "IMAGE_ALREADY_ATTACHED"


async def test_key_of_another_language_is_conflict(
    api: AsyncClient, object_store
) -> None:
    """언어 사이로 key를 옮길 수 없다. 새로 업로드해야 한다."""
    [key] = await _keys(api, object_store, 1)
    created = await _create(api, _with(KO, [key]), EN)

    response = await api.patch(
        f"{URL}/{created['id']}", json={"translations": [_with(EN, [key])]}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "IMAGE_ALREADY_ATTACHED"
    assert (await api.get(f"{URL}/{created['id']}")).json() == created


async def test_patch_replaces_only_the_sent_language(
    api: AsyncClient, database, object_store
) -> None:
    a, b, c, d, e = await _keys(api, object_store, 5)
    created = await _create(api, _with(KO, [a, b, c]), _with(EN, [e]))

    response = await api.patch(
        f"{URL}/{created['id']}", json={"translations": [_with(KO, [c, d, a])]}
    )

    assert response.status_code == 200, response.text
    assert _images(response.json()) == {"EN": [e], "KO": [c, d, a]}
    got = await api.get(f"{URL}/{created['id']}")
    assert _images(got.json()) == {"EN": [e], "KO": [c, d, a]}
    assert await _status(database, b) is ImageStatus.DETACHED
    assert await _status(database, d) is ImageStatus.ATTACHED
    assert await _status(database, e) is ImageStatus.ATTACHED


async def test_patch_text_without_image_field_keeps_images(
    api: AsyncClient, database, object_store
) -> None:
    a, b = await _keys(api, object_store, 2)
    created = await _create(api, _with(KO, [a, b]))

    response = await api.patch(
        f"{URL}/{created['id']}",
        json={"type": "PERMANENT", "translations": [{**KO, "title": "바뀜"}]},
    )

    assert response.status_code == 200, response.text
    assert _images(response.json()) == {"KO": [a, b]}
    assert await _status(database, a) is ImageStatus.ATTACHED


async def test_patch_null_detaches_only_that_language(
    api: AsyncClient, database, object_store
) -> None:
    a, b = await _keys(api, object_store, 2)
    created = await _create(api, _with(KO, [a]), _with(EN, [b]))

    response = await api.patch(
        f"{URL}/{created['id']}", json={"translations": [_with(EN, None)]}
    )

    assert _images(response.json()) == {"EN": None, "KO": [a]}
    assert await _status(database, a) is ImageStatus.ATTACHED
    assert await _status(database, b) is ImageStatus.DETACHED


async def test_patch_adds_a_language_with_its_images(
    api: AsyncClient, object_store
) -> None:
    [key] = await _keys(api, object_store, 1)
    created = await _create(api, KO)

    response = await api.patch(
        f"{URL}/{created['id']}", json={"translations": [_with(EN, [key])]}
    )

    assert response.status_code == 200, response.text
    assert _images(response.json()) == {"EN": [key], "KO": None}


async def test_failed_image_rolls_back_fields_and_translations(
    api: AsyncClient, database, object_store
) -> None:
    [a] = await _keys(api, object_store, 1)
    created = await _create(api, _with(KO, [a]))

    response = await api.patch(
        f"{URL}/{created['id']}",
        json={
            "type": "PERMANENT",
            "translations": [
                {**KO, "title": "바뀜", "notice_image_uri": ["images/notice/no.webp"]}
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"
    assert (await api.get(f"{URL}/{created['id']}")).json() == created
    assert await _status(database, a) is ImageStatus.ATTACHED


async def test_delete_detaches_images_of_every_language(
    api: AsyncClient, database, object_store
) -> None:
    a, b = await _keys(api, object_store, 2)
    created = await _create(api, _with(KO, [a]), _with(EN, [b]))

    response = await api.delete(f"{URL}/{created['id']}")

    assert response.status_code == 204
    assert await _status(database, a) is ImageStatus.DETACHED
    assert await _status(database, b) is ImageStatus.DETACHED


async def test_deleting_a_translation_detaches_its_images(
    api: AsyncClient, database, object_store
) -> None:
    """연결 행은 FK cascade로 지워지므로 이미지가 ATTACHED로 남지 않게 한다."""
    a, b = await _keys(api, object_store, 2)
    created = await _create(api, _with(KO, [a]), _with(EN, [b]))

    response = await api.delete(f"{URL}/{created['id']}/translations/EN")

    assert response.status_code == 204
    assert _images((await api.get(f"{URL}/{created['id']}")).json()) == {"KO": [a]}
    assert await _status(database, a) is ImageStatus.ATTACHED
    assert await _status(database, b) is ImageStatus.DETACHED


async def test_refused_ko_translation_delete_keeps_images(
    api: AsyncClient, database, object_store
) -> None:
    [a] = await _keys(api, object_store, 1)
    created = await _create(api, _with(KO, [a]))

    response = await api.delete(f"{URL}/{created['id']}/translations/KO")

    assert response.status_code == 409
    assert await _status(database, a) is ImageStatus.ATTACHED
