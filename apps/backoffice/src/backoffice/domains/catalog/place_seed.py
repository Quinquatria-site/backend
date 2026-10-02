"""지도 좌표 장소를 한 번 넣는 진입점 (명세 §5.4).

    python -m backoffice.domains.catalog.place_seed [JSON 경로]

경로를 생략하면 이미지에 함께 들어가는 `data/map_places.json`을 쓴다.
항목마다 카테고리·구역 번호·좌표만 넣고, 운영 시간과 번역은 Backoffice
`PATCH`로 채운다. 넣은 장소는 Customer API에 빈 마커로 바로 보이므로, 새로
넣은 것이 있으면 commit 뒤 `places` ISR 재검증을 보낸다.

파일 전체가 한 transaction이다. 같은 구역 번호가 같은 좌표에 이미 있으면
건너뛰므로 다시 실행해도 안전하다. 다른 좌표에 있으면 덮어쓰지 않고
전체를 되돌린다.
"""

import asyncio
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Protocol

import httpx
from pydantic import AfterValidator, TypeAdapter
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from backoffice.config import get_settings
from backoffice.crud.schemas import RequestModel
from backoffice.domains.catalog.schemas import Coordinate, Position
from backoffice.revalidation.events import RevalidationTag
from backoffice.revalidation.sender import RevalidationSender
from quinquatria_persistence import Database
from quinquatria_persistence.enums import CategoryCode
from quinquatria_persistence.models import Category, Place

BUNDLED = Path(__file__).with_name("data") / "map_places.json"


class SeedPlace(RequestModel):
    code: CategoryCode
    category_sequence: Position
    x: Coordinate
    y: Coordinate


def _unique_pairs(places: list[SeedPlace]) -> list[SeedPlace]:
    pairs = [(place.code, place.category_sequence) for place in places]
    if len(set(pairs)) != len(pairs):
        raise ValueError("code and category_sequence must not repeat")
    return places


_FILE = TypeAdapter(Annotated[list[SeedPlace], AfterValidator(_unique_pairs)])


def load(path: Path | str) -> list[SeedPlace]:
    """파일을 검증한다. 잘못된 항목은 DB에 닿기 전에 ValidationError다."""
    return _FILE.validate_json(Path(path).read_bytes())


class SeedConflict(Exception):
    """같은 구역 번호의 장소가 다른 좌표에 이미 있다."""


@dataclass(frozen=True)
class SeedReport:
    created: int
    skipped: int


async def seed_places(session: AsyncSession, places: Sequence[SeedPlace]) -> SeedReport:
    category_ids = dict(
        (await session.execute(select(Category.code, Category.id))).tuples().all()
    )
    missing = {place.code for place in places} - category_ids.keys()
    if missing:
        raise SeedConflict(f"시드 카테고리가 없습니다: {sorted(missing)}")

    wanted = {
        (category_ids[place.code], place.category_sequence): place for place in places
    }
    existing = await session.execute(
        select(Place.category_id, Place.category_sequence, Place.x, Place.y).where(
            tuple_(Place.category_id, Place.category_sequence).in_(wanted)
        )
    )
    skipped = 0
    for category_id, sequence, x, y in existing:
        place = wanted.pop((category_id, sequence))
        if (place.x, place.y) != (x, y):
            raise SeedConflict(
                f"{place.code} {sequence}이 이미 다른 좌표({x}, {y})에 있습니다."
            )
        skipped += 1

    session.add_all(
        Place(category_id=category_id, category_sequence=sequence, x=place.x, y=place.y)
        for (category_id, sequence), place in wanted.items()
    )
    await session.flush()
    return SeedReport(created=len(wanted), skipped=skipped)


class _Sender(Protocol):
    async def send_automatic(self, tag: RevalidationTag) -> None: ...


async def run(database: Database, sender: _Sender, path: Path | str) -> SeedReport:
    """파일을 넣고, 새 장소가 있으면 commit 뒤에 재검증을 보낸다."""
    places = load(path)
    async with database.transaction() as session:
        report = await seed_places(session, places)
    if report.created:
        await sender.send_automatic(RevalidationTag.PLACES)
    return report


async def main(path: Path) -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        # API 프로세스와 같은 전송 조건: 재시도·리다이렉트 없음 (명세 §7.1).
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(retries=0), follow_redirects=False
        ) as client:
            sender = RevalidationSender(
                client, settings.user_site_url, settings.revalidate_secret
            )
            report = await run(database, sender, path)
    finally:
        await database.dispose()
    logging.getLogger(__name__).info(
        "장소 시드 완료: created=%s skipped=%s", report.created, report.skipped
    )


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]) if len(sys.argv) > 1 else BUNDLED))
