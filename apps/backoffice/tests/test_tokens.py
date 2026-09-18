"""명세 §4.2의 JWT 계약을 검증한다.

모든 실패는 사유를 구분하지 않고 같은 401로 수렴해야 한다. 사유가 드러나면
공격자가 어떤 조작이 통했는지 알 수 있다.
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest

from backoffice.auth.tokens import (
    ALGORITHM,
    AUDIENCE,
    ISSUER,
    SUBJECT,
    issue_token,
    verify_token,
)
from common.errors import ApiError, ErrorCode

KEY = "k" * 32
OTHER_KEY = "z" * 32
TTL = 18000
# PyJWT가 iat/exp를 실제 시계로 검증하므로 고정 날짜를 쓰면 테스트가 실패하거나
# 의도와 다른 이유로 통과한다.
NOW = datetime.now(UTC)


def _claims(**overrides: object) -> dict[str, object]:
    issued_at = int(NOW.timestamp())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": SUBJECT,
        "iat": issued_at,
        "exp": issued_at + TTL,
        "jti": "550e8400-e29b-41d4-a716-446655440000",
    }
    claims.update(overrides)
    return claims


def _segment(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _forge(header: dict[str, object], signature: str = "") -> str:
    """서명 검증을 우회하려는 토큰을 손으로 만든다.

    PyJWT는 이런 토큰의 생성을 막으므로 직접 조립한다.
    """
    return f"{_segment(header)}.{_segment(_claims())}.{signature}"


def test_issued_token_carries_the_spec_claims() -> None:
    token = issue_token(signing_key=KEY, now=NOW, ttl_seconds=TTL)

    claims = jwt.decode(
        token, KEY, algorithms=[ALGORITHM], issuer=ISSUER, audience=AUDIENCE
    )

    assert claims["iss"] == ISSUER
    assert claims["aud"] == AUDIENCE
    assert claims["sub"] == SUBJECT
    assert claims["iat"] == int(NOW.timestamp())
    assert claims["exp"] == claims["iat"] + TTL
    assert UUID(claims["jti"])


def test_each_issuance_gets_a_new_jti() -> None:
    first = issue_token(signing_key=KEY, now=NOW, ttl_seconds=TTL)
    second = issue_token(signing_key=KEY, now=NOW, ttl_seconds=TTL)

    assert (
        jwt.decode(
            first, KEY, algorithms=[ALGORITHM], issuer=ISSUER, audience=AUDIENCE
        )["jti"]
        != jwt.decode(
            second, KEY, algorithms=[ALGORITHM], issuer=ISSUER, audience=AUDIENCE
        )["jti"]
    )


def test_round_trip_succeeds() -> None:
    token = issue_token(signing_key=KEY, now=datetime.now(UTC), ttl_seconds=TTL)

    assert verify_token(token, signing_key=KEY)["sub"] == SUBJECT


@pytest.mark.parametrize(
    ("name", "token_factory"),
    [
        (
            "expired",
            lambda: issue_token(
                signing_key=KEY,
                now=datetime.now(UTC) - timedelta(seconds=2 * TTL),
                ttl_seconds=TTL,
            ),
        ),
        ("alg_none", lambda: _forge({"alg": "none", "typ": "JWT"})),
        (
            "alg_rs256",
            lambda: _forge({"alg": "RS256", "typ": "JWT"}, "not-a-signature"),
        ),
        ("wrong_issuer", lambda: jwt.encode(_claims(iss="attacker"), KEY, ALGORITHM)),
        (
            "wrong_audience",
            lambda: jwt.encode(_claims(aud="other-api"), KEY, ALGORITHM),
        ),
        ("wrong_subject", lambda: jwt.encode(_claims(sub="root"), KEY, ALGORITHM)),
        ("non_uuid_jti", lambda: jwt.encode(_claims(jti="not-a-uuid"), KEY, ALGORITHM)),
        ("malformed", lambda: "this.is.not.a.jwt"),
        ("empty", lambda: ""),
    ],
)
def test_invalid_tokens_are_rejected(name: str, token_factory) -> None:
    with pytest.raises(ApiError) as caught:
        verify_token(token_factory(), signing_key=KEY)

    assert caught.value.code == ErrorCode.INVALID_TOKEN
    assert caught.value.status_code == 401
    assert caught.value.headers == {"WWW-Authenticate": "Bearer"}
    assert caught.value.details == []


def test_missing_required_claim_is_rejected() -> None:
    without_jti = {key: value for key, value in _claims().items() if key != "jti"}

    with pytest.raises(ApiError) as caught:
        verify_token(jwt.encode(without_jti, KEY, ALGORITHM), signing_key=KEY)

    assert caught.value.code == ErrorCode.INVALID_TOKEN


def test_signature_from_another_key_is_rejected() -> None:
    token = issue_token(signing_key=OTHER_KEY, now=datetime.now(UTC), ttl_seconds=TTL)

    with pytest.raises(ApiError) as caught:
        verify_token(token, signing_key=KEY)

    assert caught.value.code == ErrorCode.INVALID_TOKEN


def test_failure_message_does_not_reveal_the_reason() -> None:
    expired = issue_token(
        signing_key=KEY,
        now=datetime.now(UTC) - timedelta(seconds=2 * TTL),
        ttl_seconds=TTL,
    )

    with pytest.raises(ApiError) as expired_error:
        verify_token(expired, signing_key=KEY)
    with pytest.raises(ApiError) as malformed_error:
        verify_token("garbage", signing_key=KEY)

    assert expired_error.value.message == malformed_error.value.message
