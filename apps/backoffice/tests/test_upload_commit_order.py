"""발급 응답은 행이 commit된 뒤에만 나가야 한다.

commit이 응답보다 늦으면 client는 정상 upload URL과 key를 받았는데 `IMAGE`
행은 없는 상태가 된다. 그 key는 업로드해도 연결할 수 없고, 원장에 없으니
cleanup이 객체를 지운다. client는 실패를 알 방법이 없다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backoffice.auth.dependencies import get_object_store
from backoffice.auth.tokens import issue_token
from backoffice.config import Settings, get_settings
from backoffice.main import create_app

from ._auth import SIGNING_KEY
from ._images import FakeObjectStore, RecordingSession

PATH = "/api/v1/uploads/images/presigned-url"


class CommitFailingDatabase:
    """행은 받아들이지만 transaction 종료에서 실패하는 `Database` 대역."""

    def __init__(self) -> None:
        self.session = RecordingSession()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[RecordingSession]:
        yield self.session
        # `session.begin()`의 종료 commit이 실패하는 상황이다.
        raise RuntimeError("commit failed")


@pytest.fixture
def failing_database() -> CommitFailingDatabase:
    return CommitFailingDatabase()


@pytest.fixture
def commit_failing_client(
    settings: Settings, failing_database: CommitFailingDatabase
) -> TestClient:
    """`get_session`을 그대로 두고 transaction 종료만 실패시킨다."""
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_object_store] = FakeObjectStore
    application.state.database = failing_database
    return TestClient(application, raise_server_exceptions=False)


def _bearer() -> dict[str, str]:
    token = issue_token(
        signing_key=SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=18000
    )
    return {"Authorization": f"Bearer {token}"}


def _body() -> dict:
    return {
        "resource_type": "PLACE_IMAGE",
        "content_type": "image/webp",
        "size": 348210,
    }


def test_failed_commit_does_not_return_an_upload_url(
    commit_failing_client: TestClient, failing_database: CommitFailingDatabase
) -> None:
    response = commit_failing_client.post(PATH, json=_body(), headers=_bearer())

    # 행을 담고 flush까지 성공한 뒤 commit만 실패한 경로임을 확인한다.
    assert failing_database.session.added
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_SERVER_ERROR"
    assert "upload_url" not in response.text
