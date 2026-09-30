"""한 transaction에서 같은 ISR 태그를 한 번만 예약한다."""

from sqlalchemy.ext.asyncio import AsyncSession

from backoffice.revalidation.events import (
    RevalidationTag,
    mark_changed,
    pop_tags,
)


async def test_tags_dedupe_in_first_seen_order_and_are_popped_once() -> None:
    async with AsyncSession() as session:
        for tag in (
            RevalidationTag.CATEGORIES,
            RevalidationTag.CATEGORIES,
            RevalidationTag.PLACES,
            RevalidationTag.PERFORMANCES,
            RevalidationTag.NOTICES,
            RevalidationTag.LOST_ITEMS,
            RevalidationTag.PLACES,
        ):
            mark_changed(session, tag)

        assert pop_tags(session) == tuple(RevalidationTag)
        assert pop_tags(session) == ()
