"""인프라 프로브용 `GET /healthcheck`.

API 버전과 무관하게 고정된 경로라 `/api/v1` 밖에 둔다. 앱이 넘긴 확인 함수가
제한 시간 안에 끝나면 200, 실패하거나 시간을 넘기면 503이다.
"""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from common.app import create_api_app


def _client(health_check=None, timeout: float = 0.2) -> TestClient:
    return TestClient(
        create_api_app(
            title="Healthcheck Test API",
            health_check=health_check,
            health_check_timeout=timeout,
        )
    )


async def _healthy(application: FastAPI) -> None:
    return None


async def _broken(application: FastAPI) -> None:
    raise ConnectionError("database unreachable")


async def _hanging(application: FastAPI) -> None:
    await asyncio.sleep(10)


def test_healthy_dependency_returns_ok() -> None:
    response = _client(_healthy).get("/healthcheck")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_failing_dependency_returns_service_unavailable() -> None:
    response = _client(_broken).get("/healthcheck")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_dependency_that_hangs_is_cut_off_by_the_timeout() -> None:
    """DB 연결에는 타임아웃이 없어, 제한이 없으면 프로브가 응답 없이 매달린다."""
    response = _client(_hanging, timeout=0.1).get("/healthcheck")

    assert response.status_code == 503


def test_without_a_check_only_the_process_is_reported() -> None:
    response = _client().get("/healthcheck")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_check_receives_the_application() -> None:
    """앱은 lifespan이 `app.state`에 둔 자원으로 확인한다."""
    seen: list[FastAPI] = []

    async def record(application: FastAPI) -> None:
        seen.append(application)

    client = _client(record)
    client.get("/healthcheck")

    assert seen == [client.app]


def test_healthcheck_is_outside_the_versioned_api() -> None:
    assert _client(_healthy).get("/api/v1/healthcheck").status_code == 404


def test_healthcheck_is_not_part_of_the_api_schema() -> None:
    schema = _client(_healthy).get("/openapi.json").json()

    assert "/healthcheck" not in schema["paths"]
