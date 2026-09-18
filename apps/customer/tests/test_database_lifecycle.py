"""설정 시점, 앱별 DB 소유권과 요청별 세션 종료를 mock으로 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from customer import main
from customer.api.dependencies import ReadSession


def _recording_database():
    database = Mock(dispose=AsyncMock())
    sessions = []
    closed_sessions = []

    @asynccontextmanager
    async def session_context():
        session = AsyncMock(spec=AsyncSession)
        sessions.append(session)
        try:
            yield session
        finally:
            closed_sessions.append(session)

    database.session.side_effect = session_context
    return database, sessions, closed_sessions


def test_factory_does_not_read_configuration_or_create_database(monkeypatch):
    database_factory = Mock(side_effect=AssertionError("DB created before startup"))
    monkeypatch.setattr(main, "Database", database_factory)
    monkeypatch.setattr(
        main.os.environ,
        "get",
        Mock(side_effect=AssertionError("env read before startup")),
    )

    application = main.create_app()

    assert application.title == "Quinquatria Customer API"
    database_factory.assert_not_called()


@pytest.mark.parametrize("explicit_url", [None, ""])
def test_startup_requires_database_url(monkeypatch, explicit_url):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="^DATABASE_URL is required$"):
        with TestClient(main.create_app(database_url=explicit_url)):
            pass


@pytest.mark.parametrize("explicit", [False, True])
def test_configuration_is_resolved_at_startup_and_database_is_disposed(
    monkeypatch, explicit
):
    database = Mock(dispose=AsyncMock())
    factory = Mock(return_value=database)
    monkeypatch.setattr(main, "Database", factory)
    explicit_url = "postgresql://localhost/explicit" if explicit else None
    application = main.create_app(database_url=explicit_url)
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/environment")

    with TestClient(application) as client:
        assert client.get("/api/v1/").status_code == 200
        assert application.state.database is database
        factory.assert_called_once_with(
            explicit_url or "postgresql://localhost/environment"
        )
        database.dispose.assert_not_awaited()

    database.dispose.assert_awaited_once()
    assert not hasattr(application.state, "database")


async def test_database_is_disposed_when_lifespan_body_raises(monkeypatch):
    database = Mock(dispose=AsyncMock())
    monkeypatch.setattr(main, "Database", Mock(return_value=database))
    application = main.create_app(database_url="postgresql://localhost/lifespan")

    with pytest.raises(RuntimeError, match="body failed"):
        async with application.router.lifespan_context(application):
            raise RuntimeError("body failed")

    database.dispose.assert_awaited_once()
    assert not hasattr(application.state, "database")


async def test_concurrent_requests_use_independent_sessions_and_close_them(
    monkeypatch,
):
    database, sessions, closed_sessions = _recording_database()
    monkeypatch.setattr(main, "Database", Mock(return_value=database))
    application = main.create_app(database_url="postgresql://localhost/customer")
    barrier = asyncio.Barrier(2)

    @application.get("/session-probe")
    async def probe(session: ReadSession):
        await barrier.wait()
        return {"session_id": id(session)}

    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            responses = await asyncio.wait_for(
                asyncio.gather(
                    client.get("/session-probe"), client.get("/session-probe")
                ),
                timeout=10,
            )

        assert [response.status_code for response in responses] == [200, 200]
        assert len(sessions) == 2 and sessions[0] is not sessions[1]
        assert {id(session) for session in closed_sessions} == {
            id(session) for session in sessions
        }

    database.dispose.assert_awaited_once()


async def test_request_error_still_closes_session(monkeypatch):
    database, sessions, closed_sessions = _recording_database()
    monkeypatch.setattr(main, "Database", Mock(return_value=database))
    application = main.create_app(database_url="postgresql://localhost/customer")

    @application.get("/failed-session-probe")
    async def probe(session: ReadSession):
        assert session is sessions[0]
        raise RuntimeError("request failed")

    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get("/failed-session-probe")

        assert response.status_code == 500
        assert response.json()["code"] == "INTERNAL_SERVER_ERROR"
        assert len(sessions) == 1
        assert closed_sessions == sessions

    database.dispose.assert_awaited_once()
