"""공지 경로의 OpenAPI 오류 응답이 실제 envelope와 같은 모델을 가리키는지 확인한다."""

import pytest

from backoffice.domains.notices.routes import router
from common.app import create_api_app

NOTICE = "/api/v1/notices/{notice_id}"
TRANSLATION = "/api/v1/notices/{notice_id}/translations/{language_code}"


@pytest.fixture(scope="module")
def schema() -> dict:
    return create_api_app(title="Notice OpenAPI", router=router).openapi()


@pytest.fixture(scope="module")
def paths(schema: dict) -> dict:
    return schema["paths"]


def _schema_ref(paths: dict, path: str, method: str, status: str) -> str:
    response = paths[path][method]["responses"][status]
    return response["content"]["application/json"]["schema"]["$ref"]


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/v1/notices", "get"),
        ("/api/v1/notices", "post"),
        (NOTICE, "get"),
        (NOTICE, "patch"),
        (NOTICE, "delete"),
        (TRANSLATION, "delete"),
    ],
)
def test_validation_error_uses_error_response(
    paths: dict, path: str, method: str
) -> None:
    assert _schema_ref(paths, path, method, "422").endswith("/ErrorResponse")


@pytest.mark.parametrize(
    ("path", "method", "status"),
    [
        (NOTICE, "get", "404"),
        (NOTICE, "patch", "404"),
        (NOTICE, "delete", "404"),
        (TRANSLATION, "delete", "404"),
        (TRANSLATION, "delete", "409"),
    ],
)
def test_domain_errors_use_error_response(
    paths: dict, path: str, method: str, status: str
) -> None:
    assert _schema_ref(paths, path, method, status).endswith("/ErrorResponse")


def test_http_validation_error_is_not_published(schema: dict) -> None:
    assert "HTTPValidationError" not in schema["components"]["schemas"]
