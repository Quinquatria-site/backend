"""Create shared festival resources and translations.

Revision ID: 0001_shared_persistence
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_shared_persistence"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

language_code = postgresql.ENUM(
    "CHN", "EN", "KO", name="language_code", create_type=False
)
category_code = postgresql.ENUM(
    "PUB",
    "BOOTH",
    "FOODTRUCK",
    "MEDI",
    "BRACELET",
    name="category_code",
    create_type=False,
)
performance_type = postgresql.ENUM(
    "ARTIST", "STUDENT", "SPECIAL", name="performance_type", create_type=False
)
notice_type = postgresql.ENUM(
    "PERMANENT", "GENERAL", name="notice_type", create_type=False
)


def upgrade() -> None:
    """Create the initial schema, including independently managed enum types."""
    bind = op.get_bind()
    for enum_type in (language_code, category_code, performance_type, notice_type):
        enum_type.create(bind, checkfirst=False)

    op.create_table(
        "category",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("code", category_code, nullable=False),
        sa.Column("category_icon_uri", sa.Text(), nullable=True),
        sa.CheckConstraint("id > 0", name=op.f("ck_category_id_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category")),
    )
    op.create_index(op.f("ix_category_code_id"), "category", ["code", "id"])
    op.create_table(
        "category_translation",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("language_code", language_code, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.CheckConstraint("id > 0", name=op.f("ck_category_translation_id_positive")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["category.id"],
            name=op.f("fk_category_translation_category_id_category"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category_translation")),
        sa.UniqueConstraint(
            "category_id",
            "language_code",
            name=op.f("uq_category_translation_category_id_language_code"),
        ),
    )
    op.create_table(
        "place",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("category_sequence", sa.Integer(), nullable=False),
        sa.Column("x", sa.Double(), nullable=False),
        sa.Column("y", sa.Double(), nullable=False),
        sa.Column("start_hour", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_hour", sa.DateTime(timezone=True), nullable=False),
        sa.Column("place_image_uri", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.CheckConstraint("id > 0", name=op.f("ck_place_id_positive")),
        sa.CheckConstraint(
            "category_sequence >= 1", name=op.f("ck_place_category_sequence_positive")
        ),
        sa.CheckConstraint(
            "end_hour >= start_hour", name=op.f("ck_place_hours_ordered")
        ),
        sa.CheckConstraint(
            "place_image_uri IS NULL OR cardinality(place_image_uri) >= 1",
            name=op.f("ck_place_images_nonempty"),
        ),
        sa.CheckConstraint(
            "place_image_uri IS NULL OR array_ndims(place_image_uri) = 1",
            name=op.f("ck_place_images_one_dimensional"),
        ),
        sa.CheckConstraint(
            "place_image_uri IS NULL OR "
            "CASE WHEN array_ndims(place_image_uri) = 1 "
            "THEN array_position(place_image_uri, NULL) IS NULL ELSE false END",
            name=op.f("ck_place_images_no_nulls"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["category.id"],
            name=op.f("fk_place_category_id_category"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_place")),
    )
    op.create_index(
        op.f("ix_place_category_id_category_sequence_id"),
        "place",
        ["category_id", "category_sequence", "id"],
    )
    op.create_table(
        "place_translation",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("place_id", sa.Integer(), nullable=False),
        sa.Column("language_code", language_code, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("host_college", sa.Text(), nullable=False),
        sa.Column(
            "description", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.CheckConstraint("id > 0", name=op.f("ck_place_translation_id_positive")),
        sa.ForeignKeyConstraint(
            ["place_id"],
            ["place.id"],
            name=op.f("fk_place_translation_place_id_place"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_place_translation")),
        sa.UniqueConstraint(
            "place_id",
            "language_code",
            name=op.f("uq_place_translation_place_id_language_code"),
        ),
    )
    op.create_table(
        "menu",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("place_id", sa.Integer(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.CheckConstraint("id > 0", name=op.f("ck_menu_id_positive")),
        sa.CheckConstraint("price >= 0", name=op.f("ck_menu_price_nonnegative")),
        sa.ForeignKeyConstraint(
            ["place_id"],
            ["place.id"],
            name=op.f("fk_menu_place_id_place"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_menu")),
    )
    op.create_index(op.f("ix_menu_place_id_id"), "menu", ["place_id", "id"])
    op.create_table(
        "menu_translation",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("menu_id", sa.Integer(), nullable=False),
        sa.Column("language_code", language_code, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "description", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.CheckConstraint("id > 0", name=op.f("ck_menu_translation_id_positive")),
        sa.ForeignKeyConstraint(
            ["menu_id"],
            ["menu.id"],
            name=op.f("fk_menu_translation_menu_id_menu"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_menu_translation")),
        sa.UniqueConstraint(
            "menu_id",
            "language_code",
            name=op.f("uq_menu_translation_menu_id_language_code"),
        ),
    )
    op.create_table(
        "performance",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("type", performance_type, nullable=False),
        sa.Column("image_uri", sa.Text(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id > 0", name=op.f("ck_performance_id_positive")),
        sa.CheckConstraint(
            "end_at >= start_at", name=op.f("ck_performance_times_ordered")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_performance")),
    )
    op.create_index(
        op.f("ix_performance_start_at_id"), "performance", ["start_at", "id"]
    )
    op.create_index(
        op.f("ix_performance_type_start_at_id"),
        "performance",
        ["type", "start_at", "id"],
    )
    op.create_table(
        "performance_translation",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("performance_id", sa.Integer(), nullable=False),
        sa.Column("language_code", language_code, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "description", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.CheckConstraint(
            "id > 0", name=op.f("ck_performance_translation_id_positive")
        ),
        sa.ForeignKeyConstraint(
            ["performance_id"],
            ["performance.id"],
            name=op.f("fk_performance_translation_performance_id_performance"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_performance_translation")),
        sa.UniqueConstraint(
            "performance_id",
            "language_code",
            name=op.f("uq_performance_translation_performance_id_language_code"),
        ),
    )
    op.create_table(
        "notice",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("type", notice_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("id > 0", name=op.f("ck_notice_id_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notice")),
    )
    op.create_index(op.f("ix_notice_created_at_id"), "notice", ["created_at", "id"])
    op.create_index(
        op.f("ix_notice_type_created_at_id"), "notice", ["type", "created_at", "id"]
    )
    op.create_table(
        "notice_translation",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column("language_code", language_code, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint("id > 0", name=op.f("ck_notice_translation_id_positive")),
        sa.ForeignKeyConstraint(
            ["notice_id"],
            ["notice.id"],
            name=op.f("fk_notice_translation_notice_id_notice"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notice_translation")),
        sa.UniqueConstraint(
            "notice_id",
            "language_code",
            name=op.f("uq_notice_translation_notice_id_language_code"),
        ),
    )
    op.create_table(
        "lost_item",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("is_returned", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("id > 0", name=op.f("ck_lost_item_id_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lost_item")),
    )
    op.create_index(
        op.f("ix_lost_item_created_at_id"), "lost_item", ["created_at", "id"]
    )
    op.create_index(
        op.f("ix_lost_item_is_returned_created_at_id"),
        "lost_item",
        ["is_returned", "created_at", "id"],
    )
    op.create_table(
        "lost_item_translation",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("lost_item_id", sa.Integer(), nullable=False),
        sa.Column("language_code", language_code, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "description", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column(
            "found_location", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.CheckConstraint("id > 0", name=op.f("ck_lost_item_translation_id_positive")),
        sa.ForeignKeyConstraint(
            ["lost_item_id"],
            ["lost_item.id"],
            name=op.f("fk_lost_item_translation_lost_item_id_lost_item"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lost_item_translation")),
        sa.UniqueConstraint(
            "lost_item_id",
            "language_code",
            name=op.f("uq_lost_item_translation_lost_item_id_language_code"),
        ),
    )


def downgrade() -> None:
    """Drop resources in dependency order, then remove the enum types."""
    op.drop_table("lost_item_translation")
    op.drop_table("lost_item")
    op.drop_table("notice_translation")
    op.drop_table("notice")
    op.drop_table("performance_translation")
    op.drop_table("performance")
    op.drop_table("menu_translation")
    op.drop_table("menu")
    op.drop_table("place_translation")
    op.drop_table("place")
    op.drop_table("category_translation")
    op.drop_table("category")

    bind = op.get_bind()
    for enum_type in (notice_type, performance_type, category_code, language_code):
        enum_type.drop(bind, checkfirst=False)
