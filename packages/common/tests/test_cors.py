"""브라우저에서 직접 호출하는 프론트를 위한 CORS 설정을 검증한다."""

from unittest.mock import Mock

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from common.app import CORS_ALLOW_ORIGINS_ENV, cors_origins_from_env, create_api_app

FRONT_ORIGIN = "https://front.example.com"

router = APIRouter()


@router.get("/ping")
async def ping() -> dict:
    return {"ok": True}


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/api/v1/ping",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def test_preflight_from_allowed_origin_succeeds() -> None:
    client = TestClient(
        create_api_app(title="t", router=router, cors_origins=lambda: [FRONT_ORIGIN])
    )

    response = _preflight(client, FRONT_ORIGIN)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONT_ORIGIN
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers


def test_simple_request_from_allowed_origin_gets_cors_header() -> None:
    client = TestClient(
        create_api_app(title="t", router=router, cors_origins=lambda: [FRONT_ORIGIN])
    )

    response = client.get("/api/v1/ping", headers={"Origin": FRONT_ORIGIN})

    assert response.headers["access-control-allow-origin"] == FRONT_ORIGIN


def test_preflight_from_other_origin_is_rejected() -> None:
    client = TestClient(
        create_api_app(title="t", router=router, cors_origins=lambda: [FRONT_ORIGIN])
    )

    response = _preflight(client, "https://evil.example.com")

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("cors_origins", [None, lambda: []])
def test_without_origins_no_cors_headers_are_sent(cors_origins) -> None:
    client = TestClient(
        create_api_app(title="t", router=router, cors_origins=cors_origins)
    )

    response = client.get("/api/v1/ping", headers={"Origin": FRONT_ORIGIN})

    assert "access-control-allow-origin" not in response.headers


def test_origins_are_resolved_on_first_call_not_at_creation() -> None:
    """앱 생성과 import는 설정을 읽지 않는다는 두 앱의 계약을 지킨다."""
    provider = Mock(return_value=[FRONT_ORIGIN])
    client = TestClient(create_api_app(title="t", router=router, cors_origins=provider))
    provider.assert_not_called()

    client.get("/api/v1/ping", headers={"Origin": FRONT_ORIGIN})
    client.get("/api/v1/ping", headers={"Origin": FRONT_ORIGIN})

    provider.assert_called_once_with()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, []),
        ("", []),
        (FRONT_ORIGIN, [FRONT_ORIGIN]),
        (
            f" {FRONT_ORIGIN} , http://localhost:3000,,",
            [FRONT_ORIGIN, "http://localhost:3000"],
        ),
    ],
)
def test_cors_origins_from_env(monkeypatch, raw, expected) -> None:
    if raw is None:
        monkeypatch.delenv(CORS_ALLOW_ORIGINS_ENV, raising=False)
    else:
        monkeypatch.setenv(CORS_ALLOW_ORIGINS_ENV, raw)

    assert cors_origins_from_env() == expected
