"""한 DB transaction에서 변경된 ISR 태그를 중복 없이 모은다."""

from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession


class RevalidationTag(StrEnum):
    CATEGORIES = "categories"
    PLACES = "places"
    PERFORMANCES = "performances"
    NOTICES = "notices"
    LOST_ITEMS = "lost-items"


_PENDING_TAGS = "backoffice.revalidation.pending_tags"


def mark_changed(session: AsyncSession, tag: RevalidationTag) -> None:
    """성공한 쓰기의 태그를 표시한다. 실제 등록은 commit 이후에만 한다."""
    session.info.setdefault(_PENDING_TAGS, {})[tag] = None


def pop_tags(session: AsyncSession) -> tuple[RevalidationTag, ...]:
    """성공적으로 commit된 session에서 태그를 최초 등록 순서로 한 번만 꺼낸다."""
    return tuple(session.info.pop(_PENDING_TAGS, {}))
