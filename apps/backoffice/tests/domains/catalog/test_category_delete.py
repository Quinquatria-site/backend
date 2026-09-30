"""카테고리와 번역 삭제 (명세 §5.2, §6)."""

from datetime import UTC, datetime

from sqlalchemy import func, select

from quinquatria_persistence.enums import ImageStatus
from quinquatria_persistence.models import CategoryTranslation, Image, Place

from ._helpers import create_category, upload


async def _add_place(database, category_id: int) -> None:
    """장소 API와 무관하게 카테고리에 장소 하나를 직접 둔다."""
    at = datetime(2026, 10, 6, 1, tzinfo=UTC)
    async with database.transaction() as session:
        session.add(
            Place(
                category_id=category_id,
                category_sequence=1,
                x=0.0,
                y=0.0,
                start_hour=at,
                end_hour=at,
            )
        )


async def test_delete_returns_empty_204_and_cascades(api, database) -> None:
    created = await create_category(
        api,
        translations=[
            {"language_code": "KO", "name": "주점"},
            {"language_code": "EN", "name": "Pub"},
        ],
    )

    response = await api.delete(f"/api/v1/categories/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers
    assert (await api.get(f"/api/v1/categories/{created['id']}")).status_code == 404
    async with database.session() as session:
        assert await session.scalar(select(func.count(CategoryTranslation.id))) == 0


async def test_delete_detaches_the_icon(api, database, object_store) -> None:
    key = await upload(api, object_store, "CATEGORY_ICON")
    created = await create_category(api, category_icon_uri=key)

    await api.delete(f"/api/v1/categories/{created['id']}")

    async with database.session() as session:
        status = await session.scalar(select(Image.status).where(Image.s3_key == key))
    assert status is ImageStatus.DETACHED


async def test_delete_missing_category_is_404(api) -> None:
    response = await api.delete("/api/v1/categories/999")

    assert response.status_code == 404


async def test_delete_with_places_is_conflict(api, database) -> None:
    created = await create_category(api)
    await _add_place(database, created["id"])

    response = await api.delete(f"/api/v1/categories/{created['id']}")

    assert response.status_code == 409
    assert response.json() == {
        "code": "DELETE_CONFLICT",
        "message": "장소가 연결된 카테고리는 삭제할 수 없습니다.",
        "details": [
            {"field": "category_id", "reason": "연결된 장소를 먼저 삭제해야 합니다."}
        ],
    }
    assert (await api.get(f"/api/v1/categories/{created['id']}")).status_code == 200


async def test_delete_translation_removes_only_that_language(api) -> None:
    created = await create_category(
        api,
        translations=[
            {"language_code": "KO", "name": "주점"},
            {"language_code": "EN", "name": "Pub"},
        ],
    )

    response = await api.delete(f"/api/v1/categories/{created['id']}/translations/EN")

    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers
    body = (await api.get(f"/api/v1/categories/{created['id']}")).json()
    assert [row["language_code"] for row in body["translations"]] == ["KO"]


async def test_delete_ko_translation_is_conflict(api) -> None:
    created = await create_category(api)

    response = await api.delete(f"/api/v1/categories/{created['id']}/translations/KO")

    assert response.status_code == 409
    assert response.json()["code"] == "DELETE_CONFLICT"


async def test_delete_absent_translation_is_404(api) -> None:
    created = await create_category(api)

    response = await api.delete(f"/api/v1/categories/{created['id']}/translations/CHN")

    assert response.status_code == 404
