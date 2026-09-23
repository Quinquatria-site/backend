"""명세 §5.2, §5.7의 공지 생성."""

from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from quinquatria_persistence import Notice, NoticeTranslation

KO = {"language_code": "KO", "title": "안전 수칙", "content": "안내를 따라 주세요."}
EN = {"language_code": "EN", "title": "Safety", "content": "Follow the staff."}
CHN = {"language_code": "CHN", "title": "安全须知", "content": "请遵循指引。"}


async def test_create_returns_201_with_sorted_translations(api: AsyncClient) -> None:
    response = await api.post(
        "/api/v1/notices", json={"type": "PERMANENT", "translations": [KO, EN, CHN]}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "PERMANENT"
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None
    assert [t["language_code"] for t in body["translations"]] == ["CHN", "EN", "KO"]
    for translation in body["translations"]:
        assert translation["notice_id"] == body["id"]
        assert isinstance(translation["id"], int)
    assert body["translations"][2] == {
        "id": body["translations"][2]["id"],
        "notice_id": body["id"],
        **KO,
    }


async def test_create_persists_notice_and_translations(
    api: AsyncClient, database
) -> None:
    response = await api.post(
        "/api/v1/notices", json={"type": "GENERAL", "translations": [KO]}
    )

    async with database.session() as session:
        notice = await session.get(Notice, response.json()["id"])
        count = await session.scalar(
            select(func.count()).select_from(NoticeTranslation)
        )
    assert notice is not None
    assert notice.type == "GENERAL"
    assert count == 1


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"type": "URGENT", "translations": [KO]}, id="unknown-type"),
        pytest.param({"type": "general", "translations": [KO]}, id="lowercase-type"),
        pytest.param({"translations": [KO]}, id="missing-type"),
        pytest.param({"type": "GENERAL"}, id="missing-translations"),
        pytest.param({"type": "GENERAL", "translations": []}, id="empty-translations"),
        pytest.param({"type": "GENERAL", "translations": [EN]}, id="no-ko"),
        pytest.param(
            {"type": "GENERAL", "translations": [KO, KO]}, id="duplicate-language"
        ),
        pytest.param(
            {"type": "GENERAL", "translations": [{**KO, "language_code": "ko"}]},
            id="lowercase-language",
        ),
        pytest.param(
            {
                "type": "GENERAL",
                "translations": [{"language_code": "KO", "title": "t"}],
            },
            id="missing-content",
        ),
        pytest.param(
            {
                "type": "GENERAL",
                "translations": [{"language_code": "KO", "content": "c"}],
            },
            id="missing-title",
        ),
        pytest.param(
            {
                "type": "GENERAL",
                "created_at": "2026-10-05T13:00:00+09:00",
                "translations": [KO],
            },
            id="server-created-at",
        ),
        pytest.param(
            {"id": 1, "type": "GENERAL", "translations": [KO]}, id="server-id"
        ),
        pytest.param(
            {"type": "GENERAL", "is_urgent": True, "translations": [KO]},
            id="urgent-flag",
        ),
        pytest.param(
            {"type": "GENERAL", "translations": [{**KO, "id": 1}]},
            id="translation-id",
        ),
        pytest.param(
            {"type": "GENERAL", "translations": [{**KO, "notice_id": 1}]},
            id="translation-fk",
        ),
    ],
)
async def test_create_rejects_invalid_body(api: AsyncClient, database, body) -> None:
    response = await api.post("/api/v1/notices", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Notice)) == 0


async def test_create_rejects_query_parameters(api: AsyncClient) -> None:
    response = await api.post(
        "/api/v1/notices?page=1", json={"type": "GENERAL", "translations": [KO]}
    )

    assert response.status_code == 422
