"""카테고리 아이콘의 연결·교체·해제 (명세 §4.6)."""

from sqlalchemy import select

from quinquatria_persistence.enums import ImageStatus
from quinquatria_persistence.models import Image

from ._helpers import create_category, upload


async def _status(database, key: str) -> ImageStatus:
    async with database.session() as session:
        return await session.scalar(select(Image.status).where(Image.s3_key == key))


async def test_create_attaches_the_icon(api, database, object_store) -> None:
    key = await upload(api, object_store, "CATEGORY_ICON")

    created = await create_category(api, category_icon_uri=key)

    assert created["category_icon_uri"] == key
    assert await _status(database, key) is ImageStatus.ATTACHED


async def test_icon_with_another_prefix_is_invalid(api, object_store) -> None:
    key = await upload(api, object_store, "MENU_IMAGE")

    response = await api.post(
        "/api/v1/categories",
        json={
            "code": "PUB",
            "category_icon_uri": key,
            "translations": [{"language_code": "KO", "name": "주점"}],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"


async def test_patch_replaces_and_detaches_the_old_icon(
    api, database, object_store
) -> None:
    old = await upload(api, object_store, "CATEGORY_ICON")
    new = await upload(api, object_store, "CATEGORY_ICON")
    created = await create_category(api, category_icon_uri=old)

    response = await api.patch(
        f"/api/v1/categories/{created['id']}", json={"category_icon_uri": new}
    )

    assert response.json()["category_icon_uri"] == new
    assert await _status(database, old) is ImageStatus.DETACHED
    assert await _status(database, new) is ImageStatus.ATTACHED


async def test_patch_null_detaches_the_icon(api, database, object_store) -> None:
    key = await upload(api, object_store, "CATEGORY_ICON")
    created = await create_category(api, category_icon_uri=key)

    response = await api.patch(
        f"/api/v1/categories/{created['id']}", json={"category_icon_uri": None}
    )

    assert response.json()["category_icon_uri"] is None
    assert await _status(database, key) is ImageStatus.DETACHED


async def test_failed_icon_rolls_back_every_change(api, object_store) -> None:
    """이미지 검증이 실패하면 같은 요청의 기본 필드와 번역도 남지 않는다."""
    created = await create_category(api)

    response = await api.patch(
        f"/api/v1/categories/{created['id']}",
        json={
            "code": "BOOTH",
            "category_icon_uri": "images/category/missing.webp",
            "translations": [{"language_code": "EN", "name": "Booth"}],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"
    assert (await api.get(f"/api/v1/categories/{created['id']}")).json() == created
