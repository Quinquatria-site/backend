"""명세 §4.3의 인가를 검증한다.

라우트 열거 테스트가 핵심이다. 이후 이슈에서 CRUD 라우트를 추가하다 보호를
빠뜨리면 여기서 깨져야 한다.
"""

from datetime import UTC, datetime, timedelta
from re import sub
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, Query
from fastapi.testclient import TestClient

from backoffice.api.router import PUBLIC_PATHS, api_router
from backoffice.auth.dependencies import require_admin
from backoffice.auth.tokens import issue_token
from backoffice.config import get_settings
from common.app import create_api_app
from common.query import NoQuery

from ._auth import OTHER_SIGNING_KEY, SIGNING_KEY

PROTECTED_PATH = "/api/v1/needs-admin"


@pytest.fixture
def protected_client(settings) -> TestClient:
    """require_admin이 걸린 임시 라우트로 의존성 자체를 검증한다."""
    guarded = APIRouter(dependencies=[Depends(require_admin)])

    @guarded.get("/needs-admin")
    async def needs_admin(query: Annotated[NoQuery, Query()]) -> dict[str, bool]:
        return {"ok": True}

    application = create_api_app(title="Authorization Test API", router=guarded)
    application.dependency_overrides[get_settings] = lambda: settings
    return TestClient(application)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_valid_token_is_accepted(protected_client: TestClient) -> None:
    token = issue_token(
        signing_key=SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=18000
    )

    response = protected_client.get(PROTECTED_PATH, headers=_bearer(token))

    assert response.status_code == 200


def test_missing_header_is_unauthorized(protected_client: TestClient) -> None:
    response = protected_client.get(PROTECTED_PATH)

    assert response.status_code == 401
    assert response.json() == {
        "code": "INVALID_TOKEN",
        "message": "유효하지 않은 토큰입니다.",
        "details": [],
    }
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Bearer",
        "Bearer ",
        "Basic abcdef",
        "Token abcdef",
        "Bearer not-a-jwt",
    ],
)
def test_malformed_authorization_headers_are_rejected(
    protected_client: TestClient, header: str
) -> None:
    response = protected_client.get(PROTECTED_PATH, headers={"Authorization": header})

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_expired_token_is_rejected(protected_client: TestClient) -> None:
    expired = issue_token(
        signing_key=SIGNING_KEY,
        now=datetime.now(UTC) - timedelta(hours=6),
        ttl_seconds=18000,
    )

    response = protected_client.get(PROTECTED_PATH, headers=_bearer(expired))

    assert response.status_code == 401


def test_token_signed_with_another_key_is_rejected(
    protected_client: TestClient,
) -> None:
    forged = issue_token(
        signing_key=OTHER_SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=18000
    )

    response = protected_client.get(PROTECTED_PATH, headers=_bearer(forged))

    assert response.status_code == 401


def test_bearer_scheme_is_case_insensitive(protected_client: TestClient) -> None:
    token = issue_token(
        signing_key=SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=18000
    )

    response = protected_client.get(
        PROTECTED_PATH, headers={"Authorization": f"bearer {token}"}
    )

    assert response.status_code == 200


def _fill(path: str) -> str:
    """`{id}` 같은 경로 변수를 아무 값으로 채워 실제 호출 가능한 경로로 만든다."""
    return sub(r"\{[^}]+\}", "1", path)


def _registered_paths(application) -> set[str]:
    """FastAPI가 실제로 노출하는 경로 목록.

    `app.routes`를 순회하지 않는 이유는 FastAPI 0.141이 `include_router`를
    평탄화하지 않고 `_IncludedRouter`로 감싸기 때문이다. 하위 라우트는 private
    API 뒤에 있으므로, 공개 계약인 OpenAPI 스키마를 기준으로 삼는다.
    """
    return set(application.openapi()["paths"])


def _unprotected(router: APIRouter, settings) -> list[str]:
    """공개 선언되지 않았는데 토큰 없이 통과하는 경로를 찾는다.

    의존성 객체를 들여다보는 대신 실제로 호출해 본다. 보호된 라우트는 본문이나
    경로 변수가 무엇이든 401로 먼저 막히므로, 401이 아니면 보호가 없는 것이다.
    """
    application = create_api_app(title="Route Audit", router=router)
    application.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(application, raise_server_exceptions=False)

    offenders = []
    for path, operations in application.openapi()["paths"].items():
        if path in PUBLIC_PATHS:
            continue
        for method in operations:
            response = client.request(method.upper(), _fill(path))
            if response.status_code != 401:
                offenders.append(f"{method.upper()} {path}")
    return offenders


def test_every_route_is_public_by_declaration_or_protected(settings) -> None:
    """공개 목록에 없는 라우트는 반드시 require_admin을 달고 있어야 한다.

    미들웨어 대신 라우터 의존성을 쓰기로 했으므로, 누락 방지는 이 테스트가 맡는다.
    """
    assert _unprotected(api_router, settings) == []


def test_the_route_audit_catches_an_unprotected_route(settings) -> None:
    """감사 자체가 헛돌지 않는지 증명한다.

    보호 라우트가 아직 하나도 없어 위 테스트는 빈 목록만 비교한다. 열거가 깨져도
    조용히 통과하는 일을 막으려면, 일부러 뚫린 라우터를 잡아내는지 봐야 한다.
    """
    leaky = APIRouter()

    @leaky.get("/forgot-to-protect")
    async def forgot_to_protect(query: Annotated[NoQuery, Query()]) -> dict[str, bool]:
        return {"ok": True}

    assert _unprotected(leaky, settings) == ["GET /api/v1/forgot-to-protect"]


def test_public_paths_are_actually_registered() -> None:
    """공개 목록에 오타가 있으면 보호 누락이 조용히 통과한다."""
    application = create_api_app(title="Route Audit", router=api_router)

    assert PUBLIC_PATHS <= _registered_paths(application)
