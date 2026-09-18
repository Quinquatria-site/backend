"""S3 접근의 경계.

Protocol로 두어 테스트가 Docker 없이 돌고, 서비스 계층이 boto3 타입에
묶이지 않는다.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ObjectHead:
    """`HeadObject`가 돌려주는 값 중 검증에 쓰는 것만 담는다."""

    content_type: str
    content_length: int


@dataclass(frozen=True)
class ObjectSummary:
    """`ListObjectsV2` 결과 한 건."""

    key: str
    last_modified: datetime


class ObjectStore(Protocol):
    """이미지 객체 저장소."""

    async def presign_put(self, key: str, *, content_type: str, expires_in: int) -> str:
        """그 key와 Content-Type에만 쓸 수 있는 PUT URL을 서명한다."""
        ...

    async def head(self, key: str) -> ObjectHead | None:
        """객체가 없으면 `None`을 돌려준다."""
        ...

    async def get_range(self, key: str, *, start: int, end: int) -> bytes:
        """끝 offset을 포함하는 범위를 읽는다 (HTTP Range 규약)."""
        ...

    async def delete(self, key: str) -> None:
        """없는 key에도 성공한다. cleanup의 재실행이 이 성질에 기댄다."""
        ...

    def list_prefix(self, prefix: str) -> AsyncIterator[ObjectSummary]:
        """prefix 아래 객체를 나열한다."""
        ...
