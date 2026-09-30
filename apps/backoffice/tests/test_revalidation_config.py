"""프론트 웹훅 설정의 런타임 이름과 앱 소유 HTTP 클라이언트."""

from fastapi.testclient import TestClient

from backoffice import main
from backoffice.config import Settings


def test_exact_runtime_names_and_secret_repr(settings, monkeypatch) -> None:
    monkeypatch.setenv("USER_SITE_URL", "https://frontend.invalid")
    monkeypatch.setenv("REVALIDATE_SECRET", "dummy-revalidation-secret")
    monkeypatch.setenv("BACKOFFICE_USER_SITE_URL", "https://wrong.invalid")
    monkeypatch.setenv("BACKOFFICE_REVALIDATE_SECRET", "wrong-secret")

    configured = Settings(
        **settings.model_dump(
            exclude={"database_url", "user_site_url", "revalidate_secret"}
        ),
        DATABASE_URL=settings.database_url,
    )

    assert configured.user_site_url == "https://frontend.invalid"
    assert configured.revalidate_secret.get_secret_value() == (
        "dummy-revalidation-secret"
    )
    assert "dummy-revalidation-secret" not in repr(configured)
    assert "wrong-secret" not in repr(configured)


def test_lifespan_owns_and_closes_shared_http_client(settings, monkeypatch) -> None:
    disposed = []

    class FakeDatabase:
        def __init__(self, url):
            assert url == settings.database_url

        async def dispose(self):
            disposed.append(True)

    monkeypatch.setattr(main, "Database", FakeDatabase)
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    app = main.create_app()
    assert "/api/v1/revalidations" not in app.openapi()["paths"]
    with TestClient(app) as client:
        assert client.get("/api/v1/").status_code == 200
        sender = app.state.revalidation_sender
        assert not sender.enabled
        assert not sender._client.is_closed
    assert sender._client.is_closed
    assert disposed == [True]
