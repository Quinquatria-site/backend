"""Let a notice hold an ordered list of images.

Revision ID: 0007_notice_image
Revises: 0006_place_coordinate_first

``notice_image`` links a notice to its images in display order, with the same
constraints as ``place_image``. ``NOTICE_IMAGE`` is appended to
``image_resource_type``.

Downgrade fails while any image uses ``NOTICE_IMAGE``. PostgreSQL cannot drop
an enum value, so the type is rebuilt without it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_notice_image"
down_revision: str | Sequence[str] | None = "0006_place_coordinate_first"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREVIOUS_RESOURCE_TYPES = (
    "CATEGORY_ICON",
    "PLACE_IMAGE",
    "MENU_IMAGE",
    "PERFORMANCE_IMAGE",
    "LOST_ITEM_IMAGE",
)


def upgrade() -> None:
    # The new value is not used in this revision, so adding it inside the
    # migration transaction is safe.
    op.execute("ALTER TYPE image_resource_type ADD VALUE 'NOTICE_IMAGE'")

    op.create_table(
        "notice_image",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.CheckConstraint("id > 0", name=op.f("ck_notice_image_id_positive")),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_notice_image_seq_positive")),
        sa.ForeignKeyConstraint(
            ["notice_id"],
            ["notice.id"],
            name=op.f("fk_notice_image_notice_id_notice"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"], ["image.id"], name=op.f("fk_notice_image_image_id_image")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notice_image")),
        sa.UniqueConstraint("image_id", name=op.f("uq_notice_image_image_id")),
        sa.UniqueConstraint(
            "notice_id",
            "seq",
            name=op.f("uq_notice_image_notice_id_seq"),
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index(
        op.f("ix_notice_image_notice_id_seq"), "notice_image", ["notice_id", "seq"]
    )


def downgrade() -> None:
    in_use = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM image WHERE resource_type = 'NOTICE_IMAGE'")
    )
    if in_use:
        raise RuntimeError(
            f"{in_use} image row(s) use NOTICE_IMAGE. Delete them before downgrading."
        )

    op.drop_index(op.f("ix_notice_image_notice_id_seq"), table_name="notice_image")
    op.drop_table("notice_image")

    labels = ", ".join(f"'{label}'" for label in _PREVIOUS_RESOURCE_TYPES)
    op.execute("ALTER TYPE image_resource_type RENAME TO image_resource_type_old")
    op.execute(f"CREATE TYPE image_resource_type AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE image ALTER COLUMN resource_type TYPE image_resource_type "
        "USING resource_type::text::image_resource_type"
    )
    op.execute("DROP TYPE image_resource_type_old")
