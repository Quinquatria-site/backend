import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from quinquatria_persistence import Base, Database

from ._data import DEFAULT_EMPTY_COLUMNS, NULLABLE_COLUMNS, TABLES, VALID_ROWS

EXPECTED_ENUMS = {
    "language_code": ["CHN", "EN", "KO"],
    "category_code": [
        "PUB",
        "BOOTH",
        "FOODTRUCK",
        "MEDI",
        "TRASHCAN",
        "PHOTOBOOTH",
        "ENTRANCE",
        "BRACELET",
        "PROMOTION",
    ],
    "performance_type": ["ARTIST", "STUDENT", "SPECIAL"],
    "notice_type": ["PERMANENT", "GENERAL"],
    "image_resource_type": [
        "CATEGORY_ICON",
        "PLACE_IMAGE",
        "MENU_IMAGE",
        "PERFORMANCE_IMAGE",
        "LOST_ITEM_IMAGE",
        "NOTICE_IMAGE",
    ],
    "image_content_type": ["image/jpeg", "image/png", "image/webp"],
    "image_status": ["UPLOADING", "UPLOADED", "ATTACHED", "DETACHED"],
}

EXPECTED_INDEXES = {
    "category": {("code", "id")},
    "place": {("category_id", "category_sequence", "id")},
    "place_image": {("place_id", "seq")},
    "menu": {("place_id", "id")},
    "performance": {("date", "seq", "id"), ("type", "date", "seq", "id")},
    "notice": {("created_at", "id"), ("type", "created_at", "id")},
    "notice_image": {("notice_id", "seq")},
    "lost_item": {("created_at", "id"), ("is_returned", "created_at", "id")},
    "image": {("status", "created_at"), ("status", "detached_at")},
}


def assert_schema(connection):
    inspector = inspect(connection)
    assert set(inspector.get_table_names()) == {*TABLES, "alembic_version"}
    assert {
        enum["name"]: enum["labels"] for enum in inspector.get_enums(schema="public")
    } == EXPECTED_ENUMS
    for table in TABLES:
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        expected_fields = {"id", *VALID_ROWS[table]}
        if table in {"notice", "lost_item"}:
            expected_fields.add("created_at")
            assert columns["created_at"]["default"] is not None
        elif table == "image":
            # image는 삽입 시 지정하지 않는 서버 관리/파생 컬럼을 추가로 갖는다.
            expected_fields |= {"byte_size", "created_at", "updated_at", "detached_at"}
            assert columns["created_at"]["default"] is not None
            assert columns["updated_at"]["default"] is not None
        elif table == "performance":
            assert columns["is_live"]["default"] == "false"
        elif table == "place":
            # 구역 장소만 쓰는 열이라 VALID_ROWS의 점 장소에는 없다.
            expected_fields.add("area")
            assert columns["is_polygon"]["default"] == "false"
        assert set(columns) == expected_fields
        assert {
            (table, column["name"]) for column in columns.values() if column["nullable"]
        } == {field for field in NULLABLE_COLUMNS if field[0] == table}
        for default_table, default_column in DEFAULT_EMPTY_COLUMNS:
            if default_table == table:
                assert columns[default_column]["default"] is not None
        assert columns["id"]["identity"]
        assert inspector.get_pk_constraint(table)["constrained_columns"] == ["id"]
        indexes = {
            tuple(index["column_names"])
            for index in inspector.get_indexes(table)
            if not index["unique"]
        }
        assert indexes == EXPECTED_INDEXES.get(table, set())

    context = MigrationContext.configure(
        connection,
        opts={"compare_type": True, "compare_server_default": True},
    )
    assert compare_metadata(context, Base.metadata) == []


def test_empty_database_upgrade_repeat_downgrade_and_reapply(
    empty_database_url, alembic_config, monkeypatch
):
    # Exercise the normal environment-variable path used by the Alembic CLI.
    monkeypatch.setenv(
        "DATABASE_URL", empty_database_url.render_as_string(hide_password=False)
    )
    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            assert inspect(connection).get_table_names() == []
            assert (
                int(connection.scalar(text("SHOW server_version_num"))) // 10000 == 18
            )

        command.upgrade(alembic_config, "head")
        with engine.connect() as connection:
            assert_schema(connection)
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            assert revision

        command.upgrade(alembic_config, "head")
        with engine.connect() as connection:
            assert_schema(connection)
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == revision
            )

        command.downgrade(alembic_config, "base")
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
            assert inspect(connection).get_enums(schema="public") == []
            assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0

        command.upgrade(alembic_config, "head")
        with engine.connect() as connection:
            assert_schema(connection)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_programmatic_migration_accepts_async_connection_bridge(
    empty_database_url, alembic_config
):
    database = Database(empty_database_url)
    try:
        async with database.engine.begin() as connection:

            def upgrade(sync_connection):
                alembic_config.attributes["connection"] = sync_connection
                command.upgrade(alembic_config, "head")

            await connection.run_sync(upgrade)
            await connection.run_sync(assert_schema)
    finally:
        await database.dispose()


SEEDED_CATEGORIES = [
    (1, "PUB", {"KO": "주점", "EN": "Pub", "CHN": "酒馆"}),
    (2, "BOOTH", {"KO": "부스", "EN": "Booth", "CHN": "摊位"}),
    (3, "FOODTRUCK", {"KO": "푸드트럭", "EN": "Food Truck", "CHN": "餐车"}),
    (4, "MEDI", {"KO": "의무실", "EN": "Medical Room", "CHN": "医务室"}),
    (5, "TRASHCAN", {"KO": "쓰레기통", "EN": "Trash Can", "CHN": "垃圾桶"}),
    (6, "PHOTOBOOTH", {"KO": "포토부스", "EN": "Photo Booth", "CHN": "拍照亭"}),
    (7, "ENTRANCE", {"KO": "무대 출입구", "EN": "Stage Entrance", "CHN": "舞台出入口"}),
    (8, "BRACELET", {"KO": "팔찌", "EN": "Bracelet", "CHN": "手环"}),
    (9, "PROMOTION", {"KO": "프로모션", "EN": "Promotion", "CHN": "促销"}),
]
"""명세 §5.3의 고정 카테고리 표."""


def _categories(connection):
    rows = connection.execute(
        text(
            "SELECT c.id, c.code::text, c.image_id, t.language_code::text, t.name "
            "FROM category AS c JOIN category_translation AS t "
            "ON t.category_id = c.id ORDER BY c.id, t.language_code"
        )
    ).all()
    seeded = {}
    for category_id, code, image_id, language, name in rows:
        assert image_id is None
        seeded.setdefault((category_id, code), {})[language] = name
    return [(key[0], key[1], names) for key, names in seeded.items()]


@pytest.fixture
def migration_engine(empty_database_url, alembic_config, monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", empty_database_url.render_as_string(hide_password=False)
    )
    engine = create_engine(empty_database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_upgrade_seeds_the_fixed_categories(migration_engine, alembic_config):
    command.upgrade(alembic_config, "head")
    with migration_engine.connect() as connection:
        assert _categories(connection) == SEEDED_CATEGORIES
        # 고정 id로 넣은 뒤에도 identity가 그 다음 값부터 발급해야 한다.
        assert (
            connection.scalar(
                text("SELECT nextval(pg_get_serial_sequence('category', 'id'))")
            )
            == 10
        )


def test_downgrade_and_reupgrade_keeps_the_seed(migration_engine, alembic_config):
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "0005_performance_date_seq")
    command.upgrade(alembic_config, "head")
    with migration_engine.connect() as connection:
        assert _categories(connection) == SEEDED_CATEGORIES


def test_upgrade_keeps_matching_rows_and_fills_missing_translations(
    migration_engine, alembic_config
):
    command.upgrade(alembic_config, "0005_performance_date_seq")
    with migration_engine.begin() as connection:
        connection.execute(text("INSERT INTO category (code) VALUES ('PUB')"))
        connection.execute(
            text(
                "INSERT INTO category_translation (category_id, language_code, name) "
                "VALUES (1, 'KO', '우리 주점')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO place (category_id, category_sequence, x, y, "
                "start_hour, end_hour) VALUES (1, 1, 0, 0, now(), now())"
            )
        )

    command.upgrade(alembic_config, "head")

    with migration_engine.connect() as connection:
        categories = _categories(connection)
        assert categories[0] == (
            1,
            "PUB",
            {"KO": "우리 주점", "EN": "Pub", "CHN": "酒馆"},
        )
        assert categories[1:] == SEEDED_CATEGORIES[1:]
        assert connection.scalar(text("SELECT category_id FROM place")) == 1


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO category (code) VALUES ('BRACELET')",
        "INSERT INTO category (code) VALUES ('BOOTH')",
    ],
    ids=["removed-code", "id-code-mismatch"],
)
def test_upgrade_refuses_categories_that_do_not_match_the_seed(
    migration_engine, alembic_config, statement
):
    """운영 데이터를 추측해 옮기지 않는다. 정리 후 다시 실행해야 한다."""
    command.upgrade(alembic_config, "0005_performance_date_seq")
    with migration_engine.begin() as connection:
        connection.execute(text(statement))

    with pytest.raises(Exception, match="category"):
        command.upgrade(alembic_config, "head")

    with migration_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0005_performance_date_seq"
        )


def test_downgrade_refuses_while_notice_images_exist(migration_engine, alembic_config):
    """enum 값을 지우면 그 값을 쓰는 image 행을 옮길 곳이 없다."""
    command.upgrade(alembic_config, "0007_notice_image")
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO image (s3_key, resource_type, content_type, "
                "declared_size, status) VALUES ('images/notice/a.webp', "
                "'NOTICE_IMAGE', 'image/webp', 1, 'UPLOADING')"
            )
        )

    with pytest.raises(Exception, match="NOTICE_IMAGE"):
        command.downgrade(alembic_config, "0006_place_coordinate_first")

    with migration_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0007_notice_image"
        )


def test_upgrade_turns_existing_places_into_points(migration_engine, alembic_config):
    command.upgrade(alembic_config, "0007_notice_image")
    with migration_engine.begin() as connection:
        connection.execute(text("INSERT INTO place (x, y) VALUES (1.5, 2.5)"))

    command.upgrade(alembic_config, "head")

    with migration_engine.connect() as connection:
        row = connection.execute(text("SELECT is_polygon, x, y, area FROM place"))
        assert tuple(row.one()) == (False, 1.5, 2.5, None)


def test_downgrade_refuses_while_polygon_places_exist(migration_engine, alembic_config):
    """x·y가 다시 필수가 되면 구역 장소를 옮길 좌표가 없다."""
    command.upgrade(alembic_config, "0008_place_polygon_area")
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO place (is_polygon, area) "
                "VALUES (true, '((0,0),(1,0),(1,1))')"
            )
        )

    with pytest.raises(Exception, match="polygon"):
        command.downgrade(alembic_config, "0007_notice_image")

    with migration_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0008_place_polygon_area"
        )


def test_downgrade_removes_unused_added_categories(migration_engine, alembic_config):
    command.upgrade(alembic_config, "head")

    command.downgrade(alembic_config, "0008_place_polygon_area")

    with migration_engine.connect() as connection:
        assert _categories(connection) == SEEDED_CATEGORIES[:6]
        (labels,) = [
            enum["labels"]
            for enum in inspect(connection).get_enums(schema="public")
            if enum["name"] == "category_code"
        ]
        assert labels == [code for _, code, _ in SEEDED_CATEGORIES[:6]]


@pytest.mark.parametrize(
    ("category_id", "code"), [(7, "ENTRANCE"), (8, "BRACELET"), (9, "PROMOTION")]
)
def test_downgrade_refuses_while_a_place_uses_an_added_category(
    migration_engine, alembic_config, category_id, code
):
    """장소를 어느 카테고리로 옮길지 추측하지 않는다."""
    command.upgrade(alembic_config, "head")
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO place (category_id, category_sequence, x, y) "
                "VALUES (:id, 1, 0, 0)"
            ),
            {"id": category_id},
        )

    with pytest.raises(Exception, match=code):
        command.downgrade(alembic_config, "0008_place_polygon_area")

    with migration_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0009_category_additions"
        )
