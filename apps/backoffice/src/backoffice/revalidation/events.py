"""한 transaction에서 발생한 변경을 commit 이후 전달할 이벤트로 모은다.

CRUD 라우트는 flush로 기본 리소스 ID를 얻은 뒤 ``mark_changed``를 호출한다.
번역을 삭제할 때도 번역 행 ID가 아니라 부모 리소스의 ID를 넘긴다.
실제 도메인 라우트 연결 전에는 테스트용 라우트로 이 계약을 검증한다.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from backoffice.revalidation.schemas import (
    RESOURCE_TARGETS,
    ResourceType,
    RevalidationRequest,
    RevalidationTarget,
)

_PENDING_EVENTS = "backoffice.revalidation.pending_events"


def _mark(session: AsyncSession, event: RevalidationRequest) -> None:
    # frozen 요청 모델을 key로 사용해 전체 (target, resource_type, id)를 비교한다.
    # dict는 최초 등록 순서를 보존한다.
    session.info.setdefault(_PENDING_EVENTS, {})[event] = None


def mark_changed(
    session: AsyncSession, resource_type: ResourceType, resource_id: int
) -> None:
    """기본 리소스 변경 또는 해당 리소스 번역 삭제를 표시한다."""
    if resource_id is None:
        raise ValueError("단건 변경에는 기본 리소스 ID가 필요합니다")
    _mark(
        session,
        RevalidationRequest(
            target=RESOURCE_TARGETS[resource_type],
            resource_type=resource_type,
            id=resource_id,
        ),
    )


def mark_performances_changed(session: AsyncSession) -> None:
    """live/reorder처럼 여러 공연이 바뀌는 작업은 ID 없이 한 번 표시한다."""
    _mark(
        session,
        RevalidationRequest(
            target=RevalidationTarget.PERFORMANCES,
            resource_type=ResourceType.PERFORMANCE,
        ),
    )


def pop_events(session: AsyncSession) -> tuple[RevalidationRequest, ...]:
    """성공적으로 commit된 session의 이벤트를 한 번만 꺼낸다."""
    return tuple(session.info.pop(_PENDING_EVENTS, {}))
