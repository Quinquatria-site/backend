"""공연 테스트가 공유하는 요청 본문과 조회 도구."""

from datetime import date as DateValue

from httpx import AsyncClient
from sqlalchemy import select

from quinquatria_persistence import Database
from quinquatria_persistence.enums import (
    ImageContentType,
    ImageResourceType,
    ImageStatus,
)
from quinquatria_persistence.models import Image, Performance

from ..._images import FakeObjectStore, put_object

WEBP = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 64
DAY_ONE = "2026-10-06"
DAY_TWO = "2026-10-07"


def body(
    title: str = "메인 공연", *, date: str = DAY_ONE, **fields: object
) -> dict[str, object]:
    return {
        "type": "ARTIST",
        "date": date,
        "translations": [{"language_code": "KO", "title": title}],
        **fields,
    }


async def create(
    api: AsyncClient, title: str = "메인 공연", **fields: object
) -> dict[str, object]:
    response = await api.post("/api/v1/performances", json=body(title, **fields))
    assert response.status_code == 201, response.text
    return response.json()


async def order_of(database: Database, date: str) -> list[tuple[int, int]]:
    """해당 일차의 `(id, seq)`를 `seq` 순서로."""
    async with database.session() as session:
        rows = await session.execute(
            select(Performance.id, Performance.seq)
            .where(Performance.date == DateValue.fromisoformat(date))
            .order_by(Performance.seq)
        )
        return [tuple(row) for row in rows.all()]


async def uploaded_image(database: Database, store: FakeObjectStore, name: str) -> str:
    """S3 객체와 `UPLOADING` 원장 행을 함께 만들고 key를 돌려준다."""
    key = f"images/performance/{name}.webp"
    put_object(store, key, body=WEBP, content_type="image/webp")
    async with database.transaction() as session:
        session.add(
            Image(
                s3_key=key,
                resource_type=ImageResourceType.PERFORMANCE_IMAGE,
                content_type=ImageContentType.WEBP,
                declared_size=len(WEBP),
                status=ImageStatus.UPLOADING,
            )
        )
    return key


async def image_status(database: Database, key: str) -> ImageStatus:
    async with database.session() as session:
        status = await session.scalar(select(Image.status).where(Image.s3_key == key))
        assert status is not None
        return status
