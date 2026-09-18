"""고아 객체를 24시간 유예 뒤에 회수한다.

삭제 후보는 두 조건의 교집합이다. DB의 이미지 참조 어디에도 없고, 고아가 된
지 유예가 지났다. 참조가 살아 있는 key는 아무리 오래돼도 후보가 아니다.

전 과정이 멱등하다. 중간에 죽어도 다시 실행하면 된다.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select

from backoffice.images.keys import PREFIXES
from backoffice.images.store import ObjectStore
from quinquatria_persistence.enums import ImageStatus
from quinquatria_persistence.models import Image

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweepReport:
    deleted: int
    failed: int
    orphans: int


async def sweep(
    session,
    store: ObjectStore,
    *,
    now: datetime,
    grace_seconds: int,
    batch_size: int,
) -> SweepReport:
    """유예가 지난 고아를 지운다."""
    cutoff = now - timedelta(seconds=grace_seconds)

    candidates = (
        (
            await session.execute(
                select(Image)
                .where(
                    or_(
                        Image.status.in_((ImageStatus.UPLOADING, ImageStatus.UPLOADED))
                        & (Image.created_at < cutoff),
                        (Image.status == ImageStatus.DETACHED)
                        & (Image.detached_at < cutoff),
                    )
                )
                .order_by(Image.id)
                .limit(batch_size)
            )
        )
        .scalars()
        .all()
    )

    deleted = 0
    failed = 0
    for image in candidates:
        try:
            await store.delete(image.s3_key)
        except Exception:
            # 삭제 실패로 행을 지우지 않는다. 다음 실행이 재시도한다.
            failed += 1
            logger.warning("이미지 삭제 실패, 다음 실행에서 재시도: id=%s", image.id)
            continue
        await session.delete(image)
        deleted += 1

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
