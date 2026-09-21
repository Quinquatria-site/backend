"""Replace object key columns with image references.

Revision ID: 0003_resource_image_fk
Revises: 0002_image_ledger

The image columns are empty at this point in the project, so the rewrite
drops them instead of migrating values. Downgrade restores the columns but
not their contents.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_resource_image_fk"
down_revision: str | Sequence[str] | None = "0002_image_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SINGLE_IMAGE = (
    ("category", "category_icon_uri"),
    ("menu", "image_url"),
    ("performance", "image_uri"),
    ("lost_item", "image_url"),
)


def upgrade() -> None:
    """Swap each object key column for a unique image foreign key."""
    for table, column in _SINGLE_IMAGE:
        op.drop_column(table, column)
        op.add_column(table, sa.Column("image_id", sa.Integer(), nullable=True))
        op.create_unique_constraint(op.f(f"uq_{table}_image_id"), table, ["image_id"])
        op.create_foreign_key(
            op.f(f"fk_{table}_image_id_image"), table, "image", ["image_id"], ["id"]
        )

    op.drop_constraint(op.f("ck_place_images_nonempty"), "place", type_="check")
    op.drop_constraint(op.f("ck_place_images_one_dimensional"), "place", type_="check")
    op.drop_constraint(op.f("ck_place_images_no_nulls"), "place", type_="check")
    op.drop_column("place", "place_image_uri")

    op.create_table(
        "place_image",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("place_id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.CheckConstraint("id > 0", name=op.f("ck_place_image_id_positive")),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_place_image_seq_positive")),
        sa.ForeignKeyConstraint(
            ["place_id"],
            ["place.id"],
            name=op.f("fk_place_image_place_id_place"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"], ["image.id"], name=op.f("fk_place_image_image_id_image")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_place_image")),
        sa.UniqueConstraint("image_id", name=op.f("uq_place_image_image_id")),
        sa.UniqueConstraint(
            "place_id",
            "seq",
            name=op.f("uq_place_image_place_id_seq"),
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index(
        op.f("ix_place_image_place_id_seq"), "place_image", ["place_id", "seq"]
    )


def downgrade() -> None:
    """Restore the object key columns. Contents are not recovered."""
    op.drop_index(op.f("ix_place_image_place_id_seq"), table_name="place_image")
    op.drop_table("place_image")

    op.add_column(
        "place",
        sa.Column("place_image_uri", postgresql.ARRAY(sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_place_images_nonempty"),
        "place",
        "place_image_uri IS NULL OR cardinality(place_image_uri) >= 1",
    )
    op.create_check_constraint(
        op.f("ck_place_images_one_dimensional"),
        "place",
        "place_image_uri IS NULL OR array_ndims(place_image_uri) = 1",
    )
    op.create_check_constraint(
        op.f("ck_place_images_no_nulls"),
        "place",
        "place_image_uri IS NULL OR "
        "CASE WHEN array_ndims(place_image_uri) = 1 "
        "THEN array_position(place_image_uri, NULL) IS NULL ELSE false END",
    )

    for table, column in reversed(_SINGLE_IMAGE):
        op.drop_constraint(
            op.f(f"fk_{table}_image_id_image"), table, type_="foreignkey"
        )
        op.drop_constraint(op.f(f"uq_{table}_image_id"), table, type_="unique")
        op.drop_column(table, "image_id")
        op.add_column(table, sa.Column(column, sa.Text(), nullable=True))
