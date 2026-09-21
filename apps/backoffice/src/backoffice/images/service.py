"""이미지 업로드 URL 발급과 연결·해제.

client가 보낸 `size`와 `content_type`은 선언일 뿐이라 발급 시점에는 형식만
본다. 실제 객체 검증은 연결 시점의 `attach`가 맡는다 (명세 §4.6).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from backoffice.images.keys import build_object_key, matches_prefix
from backoffice.images.signature import SIGNATURE_BYTES, matches
from backoffice.images.store import ObjectStore
from backoffice.images.transitions import ensure_transition
from common.errors import ApiError, ErrorCode
from quinquatria_persistence.enums import (
    ImageContentType,
    ImageResourceType,
    ImageStatus,
)
from quinquatria_persistence.models import Image

REQUIRED_HEADER_IF_NONE_MATCH = "*"
UPLOAD_METHOD = "PUT"


@dataclass(frozen=True)
class UploadTicket:
    upload_url: str
    object_key: str
    expires_in: int
    content_type: ImageContentType


def _parse_content_type(value: str) -> ImageContentType:
    """허용하지 않는 MIME은 명세 §4.5대로 INVALID_IMAGE다.

    Pydantic enum으로 두면 VALIDATION_ERROR가 나가므로 문자열로 받아
    여기서 판정한다.
    """
    try:
        return ImageContentType(value)
    except ValueError as error:
        raise ApiError(ErrorCode.INVALID_IMAGE) from error


async def issue_upload_url(
    session,
    store: ObjectStore,
    *,
    resource_type: ImageResourceType,
    content_type: str,
    size: int,
    ttl_seconds: int,
    max_bytes: int,
) -> UploadTicket:
    """선언값을 검증하고 URL과 서버 생성 key를 돌려준다."""
    parsed = _parse_content_type(content_type)

    if size > max_bytes:
        raise ApiError(ErrorCode.IMAGE_TOO_LARGE)
    if size < 1:
        raise ApiError(ErrorCode.INVALID_IMAGE)

    object_key = build_object_key(resource_type, parsed)
    session.add(
        Image(
            s3_key=object_key,
            resource_type=resource_type,
            content_type=parsed,
            declared_size=size,
            status=ImageStatus.UPLOADING,
        )
    )
    await session.flush()

    upload_url = await store.presign_put(
        object_key, content_type=parsed.value, expires_in=ttl_seconds
    )
    return UploadTicket(
        upload_url=upload_url,
        object_key=object_key,
        expires_in=ttl_seconds,
        content_type=parsed,
    )


def _invalid() -> ApiError:
    """검증 실패 사유를 응답으로 구분해 알려주지 않는다.

    어떤 검사에서 걸렸는지 알려주면 객체를 탐색하는 단서가 된다.
    """
    return ApiError(ErrorCode.INVALID_IMAGE)


async def attach(
    session,
    store: ObjectStore,
    *,
    object_key: str,
    resource_type: ImageResourceType,
    current_image_id: int | None,
    max_bytes: int,
) -> Image:
    """S3 객체를 다시 검증하고 `ATTACHED`로 옮긴다.

    호출자는 반환된 `Image.id`를 리소스의 `image_id`에 넣는다. 같은
    transaction에서 실행해야 검증과 연결이 함께 성립한다.

    행을 잠그고 읽는다. 잠그지 않으면 같은 key를 동시에 연결하는 두
    요청이 모두 `UPLOADING`을 보고 아래 검사를 통과한다. 그러면 판정이
    리소스의 unique 제약으로 밀려 `IntegrityError`가 되는데, 그것은
    명세 §4.6이 정한 409가 아니다. 상태를 읽는 순간부터 전이를 commit할
    때까지 다른 transaction이 끼어들지 못하게 해야 뒤에 온 요청도
    `ATTACHED`를 보고 `IMAGE_ALREADY_ATTACHED`로 거절된다.
    """
    if not matches_prefix(object_key, resource_type):
        raise _invalid()

    image = (
        await session.execute(
            select(Image).where(Image.s3_key == object_key).with_for_update()
        )
    ).scalar_one_or_none()
    if image is None or image.resource_type is not resource_type:
        raise _invalid()

    if image.status is ImageStatus.DETACHED:
        raise _invalid()
    if image.status is ImageStatus.ATTACHED:
        if image.id != current_image_id:
            raise ApiError(ErrorCode.IMAGE_ALREADY_ATTACHED)
        return image

    head = await store.head(object_key)
    if head is None:
        raise _invalid()
    if head.content_length < 1 or head.content_length > max_bytes:
        raise _invalid()
    if head.content_type != image.content_type.value:
        raise _invalid()

    signature = await store.get_range(object_key, start=0, end=SIGNATURE_BYTES - 1)
    if not matches(signature, image.content_type):
        raise _invalid()

    ensure_transition(image.status, ImageStatus.ATTACHED)
    image.byte_size = head.content_length
    image.status = ImageStatus.ATTACHED
    return image


async def attach_many(
    session,
    store: ObjectStore,
    *,
    object_keys: Sequence[str],
    resource_type: ImageResourceType,
    current_image_ids: Iterable[int],
    max_bytes: int,
) -> list[Image]:
    """순서를 보존하며 배열 전체를 연결한다."""
    if not object_keys:
        raise ApiError(ErrorCode.VALIDATION_ERROR)
    if len(set(object_keys)) != len(object_keys):
        raise _invalid()

    owned = set(current_image_ids)
    attached = []
    for key in object_keys:
        # 이 key가 현재 리소스가 이미 쓰는 것인지 판정하려면 해당 image id가
        # 소유 집합에 있는지 봐야 한다. 그 결과를 attach에 넘겨 무변경
        # 재전송을 409가 아니라 no-op으로 만든다.
        image_id = await session.scalar(select(Image.id).where(Image.s3_key == key))
        attached.append(
            await attach(
                session,
                store,
                object_key=key,
                resource_type=resource_type,
                current_image_id=image_id if image_id in owned else None,
                max_bytes=max_bytes,
            )
        )
    return attached


async def detach(session, *, image_ids: Iterable[int], now: datetime) -> None:
    """연결을 끊고 정리 대기열에 올린다.

    S3 `DeleteObject`를 호출하지 않는다. 삭제는 cleanup이 맡으며, 이 분리가
    S3 실패로 DB transaction이 rollback되지 않음을 보장한다.
    """
    for image_id in image_ids:
        image = await session.get(Image, image_id)
        if image is None or image.status is ImageStatus.DETACHED:
            continue
        ensure_transition(image.status, ImageStatus.DETACHED)
        image.status = ImageStatus.DETACHED
        image.detached_at = now
