"""명세 §4.1의 토큰 발급 엔드포인트를 HTTP 수준에서 검증한다."""

import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backoffice.api.routes.auth import TokenRequest
from backoffice.auth.tokens import SUBJECT, verify_token
from common.errors import ErrorCode

from ._auth import ISSUANCE_CODE, SIGNING_KEY

PATH = "/api/v1/auth/token"


def test_valid_code_returns_a_usable_token(client: TestClient) -> None:
    response = client.post(PATH, json={"issuance_code": ISSUANCE_CODE})

    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["access_token", "token_type", "expires_in"]
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 18000
    assert verify_token(body["access_token"], signing_key=SIGNING_KEY)["sub"] == SUBJECT


def test_token_response_is_not_cached(client: TestClient) -> None:
    response = client.post(PATH, json={"issuance_code": ISSUANCE_CODE})

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_wrong_code_is_rejected_without_detail(client: TestClient) -> None:
    response = client.post(PATH, json={"issuance_code": "wrong-code"})

    assert response.status_code == 401
    assert response.json() == {
        "code": "INVALID_CREDENTIALS",
        "message": "인증에 실패했습니다.",
        "details": [],
    }


def test_response_never_echoes_the_issuance_code(client: TestClient) -> None:
    response = client.post(PATH, json={"issuance_code": "wrong-code"})

    assert ISSUANCE_CODE not in response.text
    assert "wrong-code" not in response.text


@pytest.mark.parametrize(
    "mistyped",
    [1234567890, ["secret-in-a-list"], {"secret": "in-a-dict"}],
)
def test_mistyped_issuance_code_does_not_reach_the_pydantic_validation_error(
    mistyped: object,
) -> None:
    """직접 생성한 경우만 덮는다. HTTP 요청 경로는 아래 테스트가 맡는다."""
    with pytest.raises(ValidationError) as raised:
        TokenRequest(issuance_code=mistyped)

    rendered = str(raised.value) + repr(raised.value)
    assert "input_value" not in rendered
    for fragment in ("1234567890", "secret-in-a-list", "in-a-dict"):
        assert fragment not in rendered


@pytest.mark.parametrize(
    "mistyped",
    [1234567890, ["secret-in-a-list"], {"secret": "in-a-dict"}],
)
def test_mistyped_issuance_code_is_not_echoed_to_the_response_or_the_log(
    client: TestClient, caplog: pytest.LogCaptureFixture, mistyped: object
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = client.post(PATH, json={"issuance_code": mistyped})

    assert response.status_code == 422
    for fragment in ("1234567890", "secret-in-a-list", "in-a-dict"):
        assert fragment not in response.text
        assert fragment not in caplog.text


def test_missing_body_field_is_a_validation_error(client: TestClient) -> None:
    response = client.post(PATH, json={})

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.VALIDATION_ERROR
    assert response.json()["details"][0]["field"] == "issuance_code"


def test_unknown_query_parameter_is_rejected(client: TestClient) -> None:
    response = client.post(
        PATH, json={"issuance_code": ISSUANCE_CODE}, params={"unknown": "1"}
    )

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.VALIDATION_ERROR
