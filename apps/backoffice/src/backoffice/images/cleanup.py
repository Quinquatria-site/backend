"""고아 객체를 24시간 유예 뒤에 회수한다.

삭제 후보는 두 조건의 교집합이다. DB의 이미지 참조 어디에도 없고, 고아가 된
지 유예가 지났다. 참조가 살아 있는 key는 아무리 오래돼도 후보가 아니다.

삭제 권한은 DB에서 원자적으로 얻는다. 후보를 읽은 뒤 객체를 지우기까지
사이에 다른 transaction이 같은 이미지를 연결할 수 있는데, 읽어둔 상태를
믿고 지우면 DB는 참조를 유지한 채 파일만 사라진다. S3 호출은 rollback되지
않으므로 되돌릴 수 있는 쪽을 먼저 확정한다. 조건부 DELETE가 행을 돌려준
뒤에야 객체를 지운다.

전 과정이 멱등하다. 중간에 죽어도 다시 실행하면 된다.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, delete, or_, select

from backoffice.images.keys import PREFIXES
from backoffice.images.store import ObjectStore
from quinquatria_persistence import Database
from quinquatria_persistence.enums import ImageStatus
from quinquatria_persistence.models import Image

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweepReport:
    deleted: int
    failed: int
    orphans: int


def _reclaimable(cutoff: datetime) -> ColumnElement[bool]:
    """유예가 지난 고아를 고르는 조건.

    후보 조회와 삭제 claim이 같은 조건을 써야 한다. claim은 그 사이에
    상태가 바뀌지 않았음을 DB에서 다시 확인하는 일이다.
    """
    return or_(
        Image.status.in_((ImageStatus.UPLOADING, ImageStatus.UPLOADED))
        & (Image.created_at < cutoff),
        (Image.status == ImageStatus.DETACHED) & (Image.detached_at < cutoff),
    )


async def sweep(
    database: Database,
    store: ObjectStore,
    *,
    now: datetime,
    grace_seconds: int,
    batch_size: int,
) -> SweepReport:
    """유예가 지난 고아를 지운다.

    건별로 transaction을 연다. 한 건의 경합이 같은 배치의 다른 회수를
    되돌리지 않는다.
    """
    cutoff = now - timedelta(seconds=grace_seconds)

    async with database.session() as session:
        candidates = (
            (
                await session.execute(
                    select(Image.id)
                    .where(_reclaimable(cutoff))
                    .order_by(Image.id)
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )

    deleted = 0
    failed = 0
    for image_id in candidates:
        async with database.transaction() as session:
            # 확인과 선점이 한 문장이라 그 사이에 attach가 끼어들 틈이 없다.
            key = await session.scalar(
                delete(Image)
                .where(Image.id == image_id, _reclaimable(cutoff))
                .returning(Image.s3_key)
                .execution_options(synchronize_session=False)
            )
        if key is None:
            # 후보를 읽은 뒤 이 이미지가 연결됐다. 객체를 건드리지 않는다.
            continue
        try:
            await store.delete(key)
        except Exception:
            # 행은 이미 없다. 남은 객체는 `_sweep_untracked`가 회수한다.
            failed += 1
            logger.warning("이미지 삭제 실패, 다음 실행에서 회수: key=%s", key)
            continue
        deleted += 1

    async with database.session() as session:
        orphans = await _sweep_untracked(
            session, store, cutoff=cutoff, budget=batch_size - deleted - failed
        )
    return SweepReport(deleted=deleted, failed=failed, orphans=orphans)


async def _sweep_untracked(
    session, store: ObjectStore, *, cutoff: datetime, budget: int
) -> int:
    """행이 아예 없는 객체를 회수한다.

    발급 transaction이 rollback됐는데 client가 이미 S3 PUT을 성공시킨 경우다.
    DB만 보는 sweep으로는 영영 찾지 못한다.
    """
    if budget <= 0:
        return 0

    removed = 0
    for prefix in PREFIXES.values():
        async for summary in store.list_prefix(prefix):
            if removed >= budget:
                return removed
            if summary.last_modified >= cutoff:
                continue
            tracked = await session.scalar(
                select(Image.id).where(Image.s3_key == summary.key)
            )
            if tracked is not None:
                continue
            try:
                await store.delete(summary.key)
            except Exception:
                logger.warning("고아 객체 삭제 실패: key=%s", summary.key)
                continue
            removed += 1
    return removed
