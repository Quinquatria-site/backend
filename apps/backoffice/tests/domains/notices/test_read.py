"""명세 §5.1의 공지 단건·목록 조회."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from quinquatria_persistence import LanguageCode, Notice, NoticeTranslation, NoticeType

from .test_create import CHN, EN, KO


async def _create(api: AsyncClient, notice_type: str = "GENERAL", *translations):
    response = await api.post(
        "/api/v1/notices",
        json={"type": notice_type, "translations": list(translations) or [KO]},
    )
    assert response.status_code == 201
    return response.json()


async def test_get_returns_all_translations(api: AsyncClient) -> None:
    created = await _create(api, "PERMANENT", KO, CHN, EN)

    response = await api.get(f"/api/v1/notices/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


@pytest.mark.parametrize("query", ["language_code=KO", "page=1", "unknown=1"])
async def test_get_rejects_query_parameters(api: AsyncClient, query: str) -> None:
    created = await _create(api)

    response = await api.get(f"/api/v1/notices/{created['id']}?{query}")

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("notice_id", ["999", "2147483648"])
async def test_get_missing_notice_is_404(api: AsyncClient, notice_id: str) -> None:
    response = await api.get(f"/api/v1/notices/{notice_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.parametrize("notice_id", ["0", "-1", "abc"])
async def test_get_invalid_id_is_422(api: AsyncClient, notice_id: str) -> None:
    response = await api.get(f"/api/v1/notices/{notice_id}")

    assert response.status_code == 422


async def _seed(database, *rows: tuple[NoticeType, datetime]) -> list[int]:
    """`created_at`을 직접 정해 정렬을 결정적으로 검증한다."""
    async with database.transaction() as session:
        notices = [
            Notice(
                type=notice_type,
                created_at=created_at,
                translations=[
                    NoticeTranslation(
                        language_code=LanguageCode.KO, title="제목", content="본문"
                    )
                ],
            )
            for notice_type, created_at in rows
        ]
        session.add_all(notices)
        await session.flush()
        return [notice.id for notice in notices]


EARLY = datetime(2026, 10, 5, 1, tzinfo=UTC)
LATE = datetime(2026, 10, 6, 1, tzinfo=UTC)


async def test_list_sorts_by_created_at_desc_then_id_desc(
    api: AsyncClient, database
) -> None:
    first, second, third, fourth = await _seed(
        database,
        (NoticeType.GENERAL, EARLY),
        (NoticeType.PERMANENT, LATE),
        (NoticeType.GENERAL, LATE),
        (NoticeType.PERMANENT, EARLY),
    )

    response = await api.get("/api/v1/notices")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [third, second, fourth, first]
    assert (body["page"], body["size"], body["total"]) == (1, 20, 4)


async def test_list_includes_all_translations(api: AsyncClient) -> None:
    created = await _create(api, "GENERAL", KO, EN, CHN)

    response = await api.get("/api/v1/notices")

    assert response.json()["items"] == [created]


async def test_list_filters_by_type(api: AsyncClient, database) -> None:
    _, permanent, _ = await _seed(
        database,
        (NoticeType.GENERAL, EARLY),
        (NoticeType.PERMANENT, EARLY),
        (NoticeType.GENERAL, LATE),
    )

    response = await api.get("/api/v1/notices?type=PERMANENT")

    body = response.json()
    assert [item["id"] for item in body["items"]] == [permanent]
    assert body["total"] == 1


async def test_list_paginates(api: AsyncClient, database) -> None:
    ids = await _seed(database, *[(NoticeType.GENERAL, EARLY)] * 5)

    second = (await api.get("/api/v1/notices?page=2&size=2")).json()
    beyond = (await api.get("/api/v1/notices?page=4&size=2")).json()

    assert [item["id"] for item in second["items"]] == [ids[2], ids[1]]
    assert (second["page"], second["size"], second["total"]) == (2, 2, 5)
    assert beyond["items"] == []
    assert beyond["total"] == 5


@pytest.mark.parametrize(
    "query",
    ["type=URGENT", "type=general", "page=0", "size=101", "language_code=KO", "x=1"],
)
async def test_list_rejects_invalid_query(api: AsyncClient, query: str) -> None:
    response = await api.get(f"/api/v1/notices?{query}")

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
