from fastapi.testclient import TestClient

from customer.main import app, create_app


def test_root() -> None:
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Hello World"}


def test_create_app_returns_new_instance() -> None:
    assert create_app() is not create_app()
