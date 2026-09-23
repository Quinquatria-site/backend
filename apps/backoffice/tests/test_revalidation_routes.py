"""수동 ISR 요청은 프론트 접수 응답을 확인한 뒤 202를 반환한다."""

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backoffice.api.routes.revalidations import get_revalidation_sender
from backoffice.auth.tokens import issue_token
from backoffice.revalidation.schemas import RESOURCE_TARGETS, RevalidationRequest
from backoffice.revalidation.sender import RevalidationFailed

from ._auth import SIGNING_KEY

PATH = "/api/v1/revalidations"
BODY = {"target": "NOTICES", "resource_type": "NOTICE", "id": 42}


class RecordingSender:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[RevalidationRequest, str]] = []
        self.fail = fail

    async def send(self, event: RevalidationRequest, *, source: str) -> None:
        await asyncio.sleep(0)
        self.calls.append((event, source))
        if self.fail:
            raise RevalidationFailed()


@pytest.fixture
def sender(client: TestClient) -> RecordingSender:
    instance = RecordingSender()
    client.app.dependency_overrides[get_revalidation_sender] = lambda: instance
    return instance


@pytest.fixture
def headers() -> dict[str, str]:
    token = issue_token(
        signing_key=SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=18000
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(("resource_type", "target"), RESOURCE_TARGETS.items())
def test_accepts_each_resource_after_receiver_acknowledges(
    client, sender, headers, resource_type, target
):
    body = {"target": target, "resource_type": resource_type, "id": 42}
    response = client.post(PATH, headers=headers, json=body)

    assert response.status_code == 202
    assert response.json() == {**body, "accepted": True}
    assert sender.calls == [(RevalidationRequest(**body), "manual")]


@pytest.mark.parametrize("extra", [{}, {"id": None}])
def test_domain_request_omits_missing_id_from_response(client, sender, headers, extra):
    body = {"target": "PERFORMANCES", "resource_type": "PERFORMANCE"}
    response = client.post(PATH, headers=headers, json={**body, **extra})

    assert response.status_code == 202
    assert response.json() == {**body, "accepted": True}
    assert sender.calls[0][0].id is None


def test_deleted_id_can_be_retried_without_a_database(client, sender, headers):
    # 이 테스트 앱에는 DB를 설정하지 않는다. 존재 조회를 추가하면 실패한다.
    response = client.post(PATH, headers=headers, json={**BODY, "id": 999999})

    assert response.status_code == 202
    assert sender.calls[0][0].id == 999999


@pytest.mark.parametrize(
    "body",
    [
        {"target": "NOTICES"},
        {"resource_type": "NOTICE"},
        {**BODY, "resource_type": "MENU"},
        {**BODY, "target": "notices"},
        {**BODY, "resource_type": "UNKNOWN"},
        {**BODY, "unexpected": True},
        *[{**BODY, "id": value} for value in (0, -1, True, "42", 1.2, 42.0)],
    ],
)
def test_invalid_request_does_not_send(client, sender, headers, body):
    response = client.post(PATH, headers=headers, json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert sender.calls == []


def test_query_parameters_are_rejected(client, sender, headers):
    response = client.post(PATH + "?id=42", headers=headers, json=BODY)

    assert response.status_code == 422
    assert sender.calls == []


def test_authentication_is_required(client, sender):
    assert client.post(PATH, json=BODY).status_code == 401
    assert sender.calls == []


def test_final_delivery_failure_returns_internal_error(client, sender, headers):
    sender.fail = True
    response = client.post(PATH, headers=headers, json=BODY)

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_SERVER_ERROR"
    assert "accepted" not in response.json()
    assert len(sender.calls) == 1
