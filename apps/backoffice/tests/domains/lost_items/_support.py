"""분실물 테스트의 요청 본문과 이미지 시드 도구."""

from datetime import datetime

from sqlalchemy import select

from quinquatria_persistence.enums import (
    ImageContentType,
    ImageResourceType,
    ImageStatus,
    LanguageCode,
)
from quinquatria_persistence.models import Image, LostItem, LostItemTranslation

from ..._images import FakeObjectStore, put_object

URL = "/api/v1/lost-items"
WEBP = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 64


def ko(title: str = "지갑", **fields: str) -> dict[str, str]:
    return {"language_code": "KO", "title": title, **fields}


def body(**overrides: object) -> dict[str, object]:
    return {"is_returned": False, "translations": [ko()], **overrides}


async def seed_image(
    database,
    store: FakeObjectStore,
    name: str,
    *,
    resource_type: ImageResourceType = ImageResourceType.LOST_ITEM_IMAGE,
    status: ImageStatus = ImageStatus.UPLOADING,
    content: bytes = WEBP,
) -> str:
    """업로드된 객체와 원장 행을 함께 만들고 object key를 돌려준다."""
    prefix = {
        ImageResourceType.LOST_ITEM_IMAGE: "images/lost-item/",
        ImageResourceType.PLACE_IMAGE: "images/place/",
    }[resource_type]
    key = f"{prefix}{name}.webp"
    put_object(store, key, body=content, content_type="image/webp")
    async with database.transaction() as session:
        session.add(
            Image(
                s3_key=key,
                resource_type=resource_type,
                content_type=ImageContentType.WEBP,
                declared_size=len(content),
                byte_size=len(content) if status is ImageStatus.ATTACHED else None,
                status=status,
            )
        )
    return key


async def image_status(database, key: str) -> ImageStatus:
    async with database.session() as session:
        return await session.scalar(select(Image.status).where(Image.s3_key == key))


async def seed_lost_item(
    database,
    *,
    created_at: datetime,
    is_returned: bool = False,
    title: str = "지갑",
) -> int:
    """`created_at`을 고정해야 하는 정렬 테스트용. API로는 정할 수 없다."""
    async with database.transaction() as session:
        item = LostItem(
            is_returned=is_returned,
            created_at=created_at,
            translations=[
                LostItemTranslation(language_code=LanguageCode.KO, title=title)
            ],
        )
        session.add(item)
        await session.flush()
        return item.id
