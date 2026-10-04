"""Add the stage entrance, bracelet and promotion categories.

Revision ID: 0009_category_additions
Revises: 0008_place_polygon_area

``ENTRANCE``, ``BRACELET`` and ``PROMOTION`` are appended to
``category_code`` and seeded as categories 7 to 9 with their translations.
The enum type is rebuilt rather than extended with ``ALTER TYPE ... ADD
VALUE`` because the new values are used by the seed rows in the same
transaction.

Downgrade fails while a place uses one of these categories. Otherwise their
icons are detached for cleanup, the rows and their translations are deleted
and the type is rebuilt without them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_category_additions"
down_revision: str | Sequence[str] | None = "0008_place_polygon_area"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREVIOUS_CODES = ("PUB", "BOOTH", "FOODTRUCK", "MEDI", "TRASHCAN", "PHOTOBOOTH")

# Frozen copy of API spec §5.3. Later edits belong in a new revision.
_SEED = (
    (7, "ENTRANCE", {"KO": "무대 출입구", "EN": "Stage Entrance", "CHN": "舞台出入口"}),
    (8, "BRACELET", {"KO": "팔찌", "EN": "Bracelet", "CHN": "手环"}),
    (9, "PROMOTION", {"KO": "프로모션", "EN": "Promotion", "CHN": "促销"}),
)
_ADDED_CODES = tuple(code for _, code, _ in _SEED)


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
    _swap_category_code((*_PREVIOUS_CODES, *_ADDED_CODES))

    bind = op.get_bind()
    for category_id, code, names in _SEED:
        # No ON CONFLICT: these ids must be free because categories are fixed.
        bind.execute(
            sa.text(
                "INSERT INTO category (id, code) OVERRIDING SYSTEM VALUE "
                "VALUES (:id, CAST(:code AS category_code))"
            ),
            {"id": category_id, "code": code},
        )
        for language, name in names.items():
            bind.execute(
                sa.text(
                    "INSERT INTO category_translation "
                    "(category_id, language_code, name) "
                    "VALUES (:id, CAST(:language AS language_code), :name)"
                ),
                {"id": category_id, "language": language, "name": name},
            )
    # Explicit ids do not advance the identity, so move it past the seed.
    bind.execute(
        sa.text(
            "SELECT setval(pg_get_serial_sequence('category', 'id'), "
            "(SELECT max(id) FROM category))"
        )
    )


def downgrade() -> None:
    codes = sa.bindparam("codes", value=_ADDED_CODES, expanding=True)
    in_use = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM place "
            "JOIN category ON category.id = place.category_id "
            "WHERE category.code::text IN :codes"
        ).bindparams(codes)
    )
    if in_use:
        raise RuntimeError(
            f"{in_use} place row(s) use {', '.join(_ADDED_CODES)}. "
            "Move or delete them before downgrading."
        )

    # Deleting a category leaves its icon ATTACHED, which cleanup never
    # reclaims. Detach it here, as the API does when it deletes a resource.
    op.execute(
        sa.text(
            "UPDATE image SET status = 'DETACHED', "
            "detached_at = current_timestamp, updated_at = current_timestamp "
            "WHERE status <> 'DETACHED' AND id IN ("
            "SELECT image_id FROM category WHERE code::text IN :codes)"
        ).bindparams(codes)
    )
    # Translations go with the rows through the foreign key cascade.
    op.execute(
        sa.text("DELETE FROM category WHERE code::text IN :codes").bindparams(codes)
    )
    _swap_category_code(_PREVIOUS_CODES)
