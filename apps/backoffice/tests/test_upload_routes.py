"""명세 §4.5의 발급 엔드포인트 계약.

DB는 세션 페이크로 대신한다. 이 Task가 검증하는 것은 HTTP 계약과 오류
분기이며, 행이 실제로 저장되는지는 Task 8의 연결 테스트가 본다.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backoffice.auth.tokens import issue_token

from ._auth import SIGNING_KEY

PATH = "/api/v1/uploads/images/presigned-url"
MAX_BYTES = 10 * 1024 * 1024


def _bearer() -> dict[str, str]:
    token = issue_token(
        signing_key=SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=18000
    )
    return {"Authorization": f"Bearer {token}"}


def _body(**overrides) -> dict:
    return {
        "resource_type": "PLACE_IMAGE",
        "content_type": "image/webp",
        "size": 348210,
    } | overrides


def test_issuing_requires_a_token(upload_client: TestClient) -> None:
    response = upload_client.post(PATH, json=_body())

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_successful_issue_returns_the_spec_shape(upload_client: TestClient) -> None:
    response = upload_client.post(PATH, json=_body(), headers=_bearer())

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "upload_url",
        "method",
        "object_key",
        "expires_in",
        "required_headers",
    }
    assert payload["method"] == "PUT"
    assert payload["expires_in"] == 300
    assert payload["required_headers"] == {
        "Content-Type": "image/webp",
        "If-None-Match": "*",
    }
    assert payload["object_key"].startswith("images/place/")
    assert payload["object_key"].endswith(".webp")


@pytest.mark.parametrize(
    ("resource_type", "prefix"),
    [
        ("CATEGORY_ICON", "images/category/"),
        ("PLACE_IMAGE", "images/place/"),
        ("MENU_IMAGE", "images/menu/"),
        ("PERFORMANCE_IMAGE", "images/performance/"),
        ("LOST_ITEM_IMAGE", "images/lost-item/"),
    ],
)
def test_each_resource_type_maps_to_its_prefix(
    upload_client: TestClient, resource_type: str, prefix: str
) -> None:
    response = upload_client.post(
        PATH, json=_body(resource_type=resource_type), headers=_bearer()
    )

    assert response.json()["object_key"].startswith(prefix)


@pytest.mark.parametrize("content_type", ["image/gif", "text/plain", "image/svg+xml"])
def test_disallowed_content_type_is_invalid_image(
    upload_client: TestClient, content_type: str
) -> None:
    """명세 §4.5는 이 경우를 VALIDATION_ERROR가 아니라 INVALID_IMAGE로 정한다."""
    response = upload_client.post(
        PATH, json=_body(content_type=content_type), headers=_bearer()
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"


def test_oversized_declaration_is_too_large(upload_client: TestClient) -> None:
    response = upload_client.post(
        PATH, json=_body(size=MAX_BYTES + 1), headers=_bearer()
    )

    assert response.status_code == 413
    assert response.json()["code"] == "IMAGE_TOO_LARGE"


def test_exactly_ten_mebibytes_is_allowed(upload_client: TestClient) -> None:
    response = upload_client.post(PATH, json=_body(size=MAX_BYTES), headers=_bearer())

    assert response.status_code == 200


@pytest.mark.parametrize("size", [0, -1])
def test_non_positive_size_is_invalid_image(
    upload_client: TestClient, size: int
) -> None:
    response = upload_client.post(PATH, json=_body(size=size), headers=_bearer())

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"


def test_unknown_resource_type_is_a_validation_error(
    upload_client: TestClient,
) -> None:
    """enum 위반은 명세 §2.3대로 VALIDATION_ERROR다."""
    response = upload_client.post(
        PATH, json=_body(resource_type="AVATAR"), headers=_bearer()
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_file_name_is_rejected(upload_client: TestClient) -> None:
    """명세 §4.5는 원본 파일명을 받지 않는다."""
    response = upload_client.post(
        PATH, json=_body(file_name="profile.jpg"), headers=_bearer()
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_query_parameters_are_rejected(upload_client: TestClient) -> None:
    response = upload_client.post(
        PATH, json=_body(), params={"page": 1}, headers=_bearer()
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_upload_url_is_returned_but_not_logged(
    upload_client: TestClient, caplog
) -> None:
    response = upload_client.post(PATH, json=_body(), headers=_bearer())

    signature = "X-Amz-Signature"
    assert signature in response.json()["upload_url"]
    assert signature not in caplog.text
