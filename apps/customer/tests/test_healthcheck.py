"""Customer 앱의 `GET /healthcheck`가 자기 DB를 확인한다."""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from customer.main import create_app

UNREACHABLE = "postgresql+psycopg://user:secret@127.0.0.1:1/missing?connect_timeout=1"


async def _get_healthcheck(application: FastAPI) -> Response:
    # TestClient는 Windows에서 psycopg async가 쓸 수 없는 이벤트 루프를 연다.
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/healthcheck")


async def test_reachable_database_is_healthy(migrated_url) -> None:
    response = await _get_healthcheck(create_app(migrated_url))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_unreachable_database_is_unavailable() -> None:
    response = await _get_healthcheck(create_app(UNREACHABLE))

    assert response.status_code == 503
