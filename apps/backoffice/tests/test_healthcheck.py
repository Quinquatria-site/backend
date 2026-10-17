"""Backoffice 앱의 `GET /healthcheck`가 자기 DB를 확인한다."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from backoffice.config import MIN_SIGNING_KEY_BYTES, get_settings
from backoffice.main import create_app

UNREACHABLE = "postgresql+psycopg://user:secret@127.0.0.1:1/missing?connect_timeout=1"


@pytest.fixture
def configure(monkeypatch: pytest.MonkeyPatch):
    def apply(database_url: str) -> None:
        monkeypatch.setenv("BACKOFFICE_ISSUANCE_CODE", "issuance-code-from-env")
        monkeypatch.setenv("BACKOFFICE_JWT_SIGNING_KEY", "k" * MIN_SIGNING_KEY_BYTES)
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("BACKOFFICE_S3_BUCKET", "quinquatria-assets")
        monkeypatch.setenv("BACKOFFICE_S3_REGION", "ap-northeast-2")

    get_settings.cache_clear()
    yield apply
    get_settings.cache_clear()


async def _get_healthcheck(application: FastAPI) -> Response:
    # TestClient는 Windows에서 psycopg async가 쓸 수 없는 이벤트 루프를 연다.
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/healthcheck")


async def test_reachable_database_is_healthy(configure, migrated_url) -> None:
    configure(migrated_url)

    response = await _get_healthcheck(create_app())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_unreachable_database_is_unavailable(configure) -> None:
    configure(UNREACHABLE)

    response = await _get_healthcheck(create_app())

    assert response.status_code == 503


async def test_healthcheck_needs_no_token(configure, migrated_url) -> None:
    """프로브는 인증 헤더를 보내지 않는다."""
    configure(migrated_url)

    response = await _get_healthcheck(create_app())

    assert response.status_code != 401
