"""Add the image lifecycle ledger.

Revision ID: 0002_image_ledger
Revises: 0001_shared_persistence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_image_ledger"
down_revision: str | Sequence[str] | None = "0001_shared_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

image_resource_type = postgresql.ENUM(
    "CATEGORY_ICON",
    "PLACE_IMAGE",
    "MENU_IMAGE",
    "PERFORMANCE_IMAGE",
    "LOST_ITEM_IMAGE",
    name="image_resource_type",
    create_type=False,
)
image_content_type = postgresql.ENUM(
    "image/jpeg",
    "image/png",
    "image/webp",
    name="image_content_type",
    create_type=False,
)
image_status = postgresql.ENUM(
    "UPLOADING",
    "UPLOADED",
    "ATTACHED",
    "DETACHED",
    name="image_status",
    create_type=False,
)


def upgrade() -> None:
    """Create the image table and its independently managed enum types."""
    bind = op.get_bind()
    for enum_type in (image_resource_type, image_content_type, image_status):
        enum_type.create(bind, checkfirst=False)

    op.create_table(
        "image",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("resource_type", image_resource_type, nullable=False),
        sa.Column("content_type", image_content_type, nullable=False),
        sa.Column("declared_size", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("status", image_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("detached_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id > 0", name=op.f("ck_image_id_positive")),
        sa.CheckConstraint(
            "declared_size BETWEEN 1 AND 10485760",
            name=op.f("ck_image_declared_size_in_range"),
        ),
        sa.CheckConstraint(
            "byte_size IS NULL OR byte_size BETWEEN 1 AND 10485760",
            name=op.f("ck_image_byte_size_in_range"),
        ),
        sa.CheckConstraint(
            "(detached_at IS NULL) = (status <> 'DETACHED')",
            name=op.f("ck_image_detached_at_matches_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_image")),
        sa.UniqueConstraint("s3_key", name=op.f("uq_image_s3_key")),
    )
    op.create_index(
        op.f("ix_image_status_created_at"), "image", ["status", "created_at"]
    )
    op.create_index(
        op.f("ix_image_status_detached_at"), "image", ["status", "detached_at"]
    )


def downgrade() -> None:
    """Drop the image table and its enum types."""
    op.drop_index(op.f("ix_image_status_detached_at"), table_name="image")
    op.drop_index(op.f("ix_image_status_created_at"), table_name="image")
    op.drop_table("image")

    bind = op.get_bind()
    for enum_type in (image_status, image_content_type, image_resource_type):
        enum_type.drop(bind, checkfirst=False)
