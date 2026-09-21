"""이미지 상태 전이 규칙.

`UPLOADING → ATTACHED` 직행을 허용하는 것이 현재의 정상 경로다. S3
ObjectCreated 이벤트는 후속 이슈라 `UPLOADED`를 거치지 않는다. 이벤트가
붙으면 `UPLOADING → UPLOADED → ATTACHED` 경로가 함께 살아난다.

`ApiError`가 아니라 `ValueError`를 던진다. 표에 없는 전이는 client 입력이
아니라 호출 코드의 결함이라 HTTP 응답으로 번역할 것이 아니다.
"""

from quinquatria_persistence.enums import ImageStatus

ALLOWED: frozenset[tuple[ImageStatus, ImageStatus]] = frozenset(
    {
        (ImageStatus.UPLOADING, ImageStatus.UPLOADED),
        (ImageStatus.UPLOADING, ImageStatus.ATTACHED),
        (ImageStatus.UPLOADED, ImageStatus.ATTACHED),
        (ImageStatus.ATTACHED, ImageStatus.DETACHED),
    }
)


def ensure_transition(current: ImageStatus, target: ImageStatus) -> None:
    """표에 없는 전이를 막는다."""
    if (current, target) not in ALLOWED:
        raise ValueError(f"허용하지 않는 이미지 상태 전이입니다: {current} -> {target}")
