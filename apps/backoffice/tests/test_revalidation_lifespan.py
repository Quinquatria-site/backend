"""앱이 HTTP 클라이언트를 소유하고, 수신 URL은 선택적으로 주입한다."""

import httpx
from fastapi.testclient import TestClient

from backoffice import main
from backoffice.config import Settings


def test_revalidation_url_can_be_set_from_environment(settings, monkeypatch):
    monkeypatch.setenv("BACKOFFICE_REVALIDATION_URL", "https://receiver.invalid/isr")

    configured = Settings(
        **settings.model_dump(exclude={"database_url", "revalidation_url"}),
        DATABASE_URL=settings.database_url,
    )

    assert configured.revalidation_url == "https://receiver.invalid/isr"


def test_client_is_owned_by_lifespan_and_missing_url_allows_start(
    settings, monkeypatch
):
    disposed = []

    class FakeDatabase:
        def __init__(self, url):
            assert url == settings.database_url

        async def dispose(self):
            disposed.append(True)

    outbound = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None))
    monkeypatch.setattr(main, "Database", FakeDatabase)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kwargs: outbound)

    app = main.create_app()
    with TestClient(app) as client:
        assert client.get("/api/v1/").status_code == 200
        assert app.state.revalidation_sender is not None
        assert not outbound.is_closed
    assert outbound.is_closed
    assert disposed == [True]
