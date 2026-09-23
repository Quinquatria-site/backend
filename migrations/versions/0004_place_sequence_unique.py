"""Make a place's sequence unique within its category.

Revision ID: 0004_place_sequence_unique
Revises: 0003_resource_image_fk

The sequence is the number in a map label such as A1, so two places in one
category must not share it. Upgrade fails if duplicates already exist; resolve
them before running it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_place_sequence_unique"
down_revision: str | Sequence[str] | None = "0003_resource_image_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reject a second place with the same category and sequence."""
    op.create_unique_constraint(
        op.f("uq_place_category_id_category_sequence"),
        "place",
        ["category_id", "category_sequence"],
    )


def downgrade() -> None:
    """Allow repeated sequences again."""
    op.drop_constraint(
        op.f("uq_place_category_id_category_sequence"), "place", type_="unique"
    )
