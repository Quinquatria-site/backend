"""Add the stage entrance category.

Revision ID: 0009_category_entrance
Revises: 0008_place_polygon_area

``ENTRANCE`` is appended to ``category_code`` and seeded as category 7 with
its translations. The enum type is rebuilt rather than extended with
``ALTER TYPE ... ADD VALUE`` because the new value is used by the seed row in
the same transaction.

Downgrade fails while a place uses the ``ENTRANCE`` category. Otherwise the
row and its translations are deleted and the type is rebuilt without it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_category_entrance"
down_revision: str | Sequence[str] | None = "0008_place_polygon_area"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREVIOUS_CODES = ("PUB", "BOOTH", "FOODTRUCK", "MEDI", "TRASHCAN", "PHOTOBOOTH")
_CODES = (*_PREVIOUS_CODES, "ENTRANCE")

# Frozen copy of API spec §5.3. Later edits belong in a new revision.
_ID = 7
_NAMES = {"KO": "무대 출입구", "EN": "Stage Entrance", "CHN": "舞台出入口"}


def _swap_category_code(codes: Sequence[str]) -> None:
    """Replace the whole type so new labels are usable in this transaction."""
    postgresql.ENUM(*codes, name="category_code_next").create(op.get_bind())
    op.execute(
        "ALTER TABLE category ALTER COLUMN code TYPE category_code_next "
        "USING code::text::category_code_next"
    )
    op.execute("DROP TYPE category_code")
    op.execute("ALTER TYPE category_code_next RENAME TO category_code")


def upgrade() -> None:
    _swap_category_code(_CODES)

    bind = op.get_bind()
    # No ON CONFLICT: id 7 must be free because categories are a fixed list.
    bind.execute(
        sa.text(
            "INSERT INTO category (id, code) OVERRIDING SYSTEM VALUE "
            "VALUES (:id, 'ENTRANCE')"
        ),
        {"id": _ID},
    )
    for language, name in _NAMES.items():
        bind.execute(
            sa.text(
                "INSERT INTO category_translation (category_id, language_code, name) "
                "VALUES (:id, CAST(:language AS language_code), :name)"
            ),
            {"id": _ID, "language": language, "name": name},
        )
    # Explicit ids do not advance the identity, so move it past the seed.
    bind.execute(
        sa.text(
            "SELECT setval(pg_get_serial_sequence('category', 'id'), "
            "(SELECT max(id) FROM category))"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    in_use = bind.scalar(
        sa.text(
            "SELECT count(*) FROM place JOIN category ON category.id = place.category_id "
            "WHERE category.code = 'ENTRANCE'"
        )
    )
    if in_use:
        raise RuntimeError(
            f"{in_use} place row(s) use the ENTRANCE category. "
            "Move or delete them before downgrading."
        )

    # Translations go with the row through the foreign key cascade.
    op.execute("DELETE FROM category WHERE code = 'ENTRANCE'")
    _swap_category_code(_PREVIOUS_CODES)
