"""이미지 테스트가 공유하는 인메모리 object store.

Docker 없이 돌리기 위한 페이크다. 서명만은 실제 botocore signer를 쓴다
(`test_object_store.py`). 서명은 네트워크 호출이 아니라 오프라인에서
진짜를 만들 수 있다.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from backoffice.images.store import ObjectHead, ObjectSummary


@dataclass
class StoredObject:
    body: bytes
    content_type: str
    last_modified: datetime


class FakeObjectStore:
    """`ObjectStore`의 인메모리 구현."""

    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}
        self.deleted: list[str] = []
        self.delete_failures: set[str] = set()
        """여기 담긴 key의 `delete`는 예외를 던진다. 재시도 경로를 시험한다."""

    async def presign_put(self, key: str, *, content_type: str, expires_in: int) -> str:
        return (
            f"https://fake.invalid/{key}"
            f"?X-Amz-Signature=fake&X-Amz-Expires={expires_in}"
        )

    async def head(self, key: str) -> ObjectHead | None:
        stored = self.objects.get(key)
        if stored is None:
            return None
        return ObjectHead(
            content_type=stored.content_type, content_length=len(stored.body)
        )

    async def get_range(self, key: str, *, start: int, end: int) -> bytes:
        stored = self.objects.get(key)
        if stored is None:
            return b""
        return stored.body[start : end + 1]

    async def delete(self, key: str) -> None:
        if key in self.delete_failures:
            raise RuntimeError(f"S3 삭제 실패 시뮬레이션: {key}")
        self.objects.pop(key, None)
        self.deleted.append(key)

    async def list_prefix(self, prefix: str) -> AsyncIterator[ObjectSummary]:
        for key, stored in sorted(self.objects.items()):
            if key.startswith(prefix):
                yield ObjectSummary(key=key, last_modified=stored.last_modified)


class RecordingSession:
    """`add`와 `flush`만 받는 최소 세션 대역.

    발급 경로는 행을 하나 넣고 끝난다. 실제 DB 동작은 Task 8의 연결
    테스트가 Postgres로 확인하므로, 계약 테스트까지 컨테이너를 요구할
    이유가 없다.
    """

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        return None


async def recording_session() -> AsyncIterator[RecordingSession]:
    yield RecordingSession()


def put_object(
    store: FakeObjectStore,
    key: str,
    *,
    body: bytes,
    content_type: str,
    last_modified: datetime | None = None,
) -> None:
    store.objects[key] = StoredObject(
        body=body,
        content_type=content_type,
        last_modified=last_modified or datetime.now(UTC),
    )
