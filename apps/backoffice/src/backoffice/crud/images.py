"""리소스의 이미지 필드를 연결·교체·해제한다 (명세 §4.6).

리소스는 `image_id`만 저장하고 API는 object key를 주고받는다. 두 표현의
변환과, 교체·해제된 이미지의 `DETACHED` 전이를 여기서 함께 처리한다.
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backoffice.images.service import attach_many, detach
from backoffice.images.store import ObjectStore
from quinquatria_persistence.enums import ImageResourceType
from quinquatria_persistence.models import Image


async def replace_image(
    session: AsyncSession,
    store: ObjectStore,
    *,
    current_image_id: int | None,
    object_key: str | None,
    resource_type: ImageResourceType,
    max_bytes: int,
    now: datetime | None = None,
) -> int | None:
    """리소스에 넣을 `image_id`를 반환한다. `None`은 연결 해제다.

    현재 key를 다시 보내면 무변경이고, 다른 key나 `None`이면 이전 이미지를
    해제한다.
    """
    current = [] if current_image_id is None else [current_image_id]
    keys = None if object_key is None else [object_key]
    new_ids = await replace_images(
        session,
        store,
        current_image_ids=current,
        object_keys=keys,
        resource_type=resource_type,
        max_bytes=max_bytes,
        now=now,
    )
    return new_ids[0] if new_ids else None


async def replace_images(
    session: AsyncSession,
    store: ObjectStore,
    *,
    current_image_ids: Sequence[int],
    object_keys: Sequence[str] | None,
    resource_type: ImageResourceType,
    max_bytes: int,
    now: datetime | None = None,
) -> list[int]:
    """순서가 있는 이미지 배열판. 새 배열에서 빠진 이미지만 해제한다."""
    new_ids: list[int] = []
    if object_keys is not None:
        images = await attach_many(
            session,
            store,
            object_keys=object_keys,
            resource_type=resource_type,
            current_image_ids=current_image_ids,
            max_bytes=max_bytes,
        )
        new_ids = [image.id for image in images]

    removed = [image_id for image_id in current_image_ids if image_id not in new_ids]
    if removed:
        await detach(session, image_ids=removed, now=now or datetime.now(UTC))
    return new_ids


async def image_keys(
    session: AsyncSession, image_ids: Iterable[int | None]
) -> dict[int, str]:
    """응답에 넣을 object key를 한 번의 조회로 모은다."""
    ids = {image_id for image_id in image_ids if image_id is not None}
    if not ids:
        return {}
    rows = await session.execute(
        select(Image.id, Image.s3_key).where(Image.id.in_(ids))
    )
    return dict(rows.tuples().all())
