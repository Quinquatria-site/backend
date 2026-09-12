from fastapi.testclient import TestClient

from backoffice.main import app, create_app

client = TestClient(app)


def test_root() -> None:
    response = client.get("/api/v1/")

    assert response.status_code == 200
    assert response.json() == {"message": "Hello World"}


def test_api_is_served_under_the_v1_prefix() -> None:
    assert client.get("/").status_code == 404


def test_root_rejects_unknown_query_parameter() -> None:
    response = client.get("/api/v1/", params={"unknown": "1"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_unknown_path_uses_the_shared_error_body() -> None:
    body = client.get("/api/v1/does-not-exist").json()

    assert body == {
        "code": "RESOURCE_NOT_FOUND",
        "message": "요청한 리소스를 찾을 수 없습니다.",
        "details": [],
    }


def test_create_app_returns_new_instance() -> None:
    assert create_app() is not create_app()
