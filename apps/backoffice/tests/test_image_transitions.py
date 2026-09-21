"""상태 전이는 표로만 허용한다.

상태를 직접 대입하면 UPLOADING에서 곧장 DETACHED로 가는 것 같은 전이가
조용히 통과한다. 그런 행은 detached_at 불변식과 sweep 판정을 어긋나게 한다.
"""

import pytest

from backoffice.images.transitions import ALLOWED, ensure_transition
from quinquatria_persistence.enums import ImageStatus

_ALL = list(ImageStatus)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ImageStatus.UPLOADING, ImageStatus.UPLOADED),
        (ImageStatus.UPLOADING, ImageStatus.ATTACHED),
        (ImageStatus.UPLOADED, ImageStatus.ATTACHED),
        (ImageStatus.ATTACHED, ImageStatus.DETACHED),
    ],
)
def test_allowed_transitions_pass(current: ImageStatus, target: ImageStatus) -> None:
    ensure_transition(current, target)


def test_uploading_cannot_skip_to_detached() -> None:
    with pytest.raises(ValueError):
        ensure_transition(ImageStatus.UPLOADING, ImageStatus.DETACHED)


def test_detached_is_terminal() -> None:
    """cleanup 대기열에 오른 key는 되살아나지 않는다."""
    for target in _ALL:
        with pytest.raises(ValueError):
            ensure_transition(ImageStatus.DETACHED, target)


def test_attached_cannot_go_back_to_uploaded() -> None:
    with pytest.raises(ValueError):
        ensure_transition(ImageStatus.ATTACHED, ImageStatus.UPLOADED)


def test_table_lists_exactly_four_transitions() -> None:
    assert len(ALLOWED) == 4


def test_no_status_transitions_to_itself() -> None:
    """같은 상태 재전송은 전이가 아니라 no-op으로 다룬다."""
    assert not {pair for pair in ALLOWED if pair[0] is pair[1]}
