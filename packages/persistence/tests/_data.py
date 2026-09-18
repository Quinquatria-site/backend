"""Independent fixtures based on the PRD fields and API data constraints."""

from datetime import UTC, datetime

from sqlalchemy import text

INSTANT = datetime(2026, 10, 6, 9, tzinfo=UTC)

VALID_IMAGE = {
    "s3_key": "images/place/first.webp",
    "resource_type": "PLACE_IMAGE",
    "content_type": "image/webp",
    "declared_size": 348210,
    "status": "UPLOADING",
}

# Insertion order follows the foreign keys. Every fresh fixture restarts identities.
VALID_ROWS = {
    "image": VALID_IMAGE,
    "category": {"code": "PUB", "image_id": None},
    "category_translation": {
        "category_id": 1,
        "language_code": "KO",
        "name": "주점",
    },
    "place": {
        "category_id": 1,
        "category_sequence": 1,
        "x": 12.25,
        "y": -7.5,
        "start_hour": INSTANT,
        "end_hour": INSTANT,
    },
    "place_translation": {
        "place_id": 1,
        "language_code": "KO",
        "name": "공학 주점",
        "host_college": "공과대학",
        "description": "행사 안내",
    },
    "place_image": {"place_id": 1, "image_id": 1, "seq": 1},
    "menu": {"place_id": 1, "image_id": None, "price": 0},
    "menu_translation": {
        "menu_id": 1,
        "language_code": "KO",
        "name": "무료 음료",
        "description": "메뉴 안내",
    },
    "performance": {
        "type": "ARTIST",
        "image_id": None,
        "start_at": INSTANT,
        "end_at": INSTANT,
    },
    "performance_translation": {
        "performance_id": 1,
        "language_code": "KO",
        "title": "공연",
        "description": "공연 안내",
    },
    "notice": {"type": "GENERAL"},
    "notice_translation": {
        "notice_id": 1,
        "language_code": "KO",
        "title": "공지",
        "content": "공지 본문",
    },
    "lost_item": {"image_id": None, "is_returned": False},
    "lost_item_translation": {
        "lost_item_id": 1,
        "language_code": "KO",
        "title": "가방",
        "description": "검정 가방",
        "found_location": "정문",
    },
}

TRANSLATIONS = tuple(name for name in VALID_ROWS if name.endswith("_translation"))
TABLES = tuple(VALID_ROWS)

NULLABLE_IMAGE_COLUMNS = {
    ("category", "image_id"),
    ("menu", "image_id"),
    ("performance", "image_id"),
    ("lost_item", "image_id"),
    # image 자체의 nullable 컬럼. VALID_IMAGE에는 없는 키라 REQUIRED_COLUMNS엔
    # 영향이 없고, test_migrations.py의 스키마 대조가 실제 컬럼 nullable
    # 여부를 이 집합과 비교하므로 여기 등록해야 한다.
    ("image", "byte_size"),
    ("image", "detached_at"),
}

DEFAULT_EMPTY_COLUMNS = {
    ("place_translation", "description"),
    ("menu_translation", "description"),
    ("performance_translation", "description"),
    ("lost_item_translation", "description"),
    ("lost_item_translation", "found_location"),
}


async def insert_row(connection, table, values):
    columns = ", ".join(values)
    parameters = ", ".join(f":{column}" for column in values)
    return await connection.scalar(
        text(f"INSERT INTO {table} ({columns}) VALUES ({parameters}) RETURNING id"),
        values,
    )
