"""Let a place start with coordinates only and seed the fixed categories.

Revision ID: 0006_place_coordinate_first
Revises: 0005_performance_date_seq

A place may now exist with only ``x`` and ``y``. Its category pair and its
hour pair are filled later, and each pair is empty or complete together.

Categories become a fixed list with fixed ids. ``BRACELET`` is replaced by
``TRASHCAN`` and ``PHOTOBOOTH``. Existing rows whose id and code match the
seed are kept with their translations and icon, and only missing translations
are added. Upgrade refuses any other existing category rather than guessing
how to move its places; resolve those rows before running it.

Downgrade fails while a place lacks a category or hours, or uses a new
category. Unused ``TRASHCAN`` and ``PHOTOBOOTH`` rows are deleted.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_place_coordinate_first"
down_revision: str | Sequence[str] | None = "0005_performance_date_seq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_CODES = ("PUB", "BOOTH", "FOODTRUCK", "MEDI", "BRACELET")
_NEW_CODES = ("PUB", "BOOTH", "FOODTRUCK", "MEDI", "TRASHCAN", "PHOTOBOOTH")
_ADDED_CODES = ("TRASHCAN", "PHOTOBOOTH")

# Frozen copy of API spec §5.3. Later edits belong in a new revision.
_SEED = (
    (1, "PUB", {"KO": "주점", "EN": "Pub", "CHN": "酒馆"}),
    (2, "BOOTH", {"KO": "부스", "EN": "Booth", "CHN": "摊位"}),
    (3, "FOODTRUCK", {"KO": "푸드트럭", "EN": "Food Truck", "CHN": "餐车"}),
    (4, "MEDI", {"KO": "의무실", "EN": "Medical Room", "CHN": "医务室"}),
    (5, "TRASHCAN", {"KO": "쓰레기통", "EN": "Trash Can", "CHN": "垃圾桶"}),
    (6, "PHOTOBOOTH", {"KO": "포토부스", "EN": "Photo Booth", "CHN": "拍照亭"}),
)

_PAIRS = {
    "category_paired": ("category_id", "category_sequence"),
    "hours_paired": ("start_hour", "end_hour"),
}


def _swap_category_code(codes: Sequence[str]) -> None:
    """PostgreSQL cannot drop an enum label, so replace the whole type."""
    postgresql.ENUM(*codes, name="category_code_next").create(op.get_bind())
    op.execute(
        "ALTER TABLE category ALTER COLUMN code TYPE category_code_next "
        "USING code::text::category_code_next"
    )
    op.execute("DROP TYPE category_code")
    op.execute("ALTER TYPE category_code_next RENAME TO category_code")


def _refuse_unknown_categories() -> None:
    expected = {(category_id, code) for category_id, code, _ in _SEED}
    rows = op.get_bind().execute(sa.text("SELECT id, code::text FROM category"))
    unknown = sorted(set(map(tuple, rows)) - expected)
    if unknown:
        raise RuntimeError(
            f"category rows {unknown} do not match the fixed seed; "
            "move their places and delete them before upgrading"
        )


def _seed_categories() -> None:
    bind = op.get_bind()
    for category_id, code, names in _SEED:
        bind.execute(
            sa.text(
                "INSERT INTO category (id, code) OVERRIDING SYSTEM VALUE "
                "VALUES (:id, CAST(:code AS category_code)) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": category_id, "code": code},
        )
        for language, name in names.items():
            bind.execute(
                sa.text(
                    "INSERT INTO category_translation "
                    "(category_id, language_code, name) "
                    "VALUES (:id, CAST(:language AS language_code), :name) "
                    "ON CONFLICT (category_id, language_code) DO NOTHING"
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


def upgrade() -> None:
    """Relax place columns into pairs, then fix the category list."""
    _refuse_unknown_categories()
    _swap_category_code(_NEW_CODES)
    op.create_unique_constraint(op.f("uq_category_code"), "category", ["code"])

    for name, (first, second) in _PAIRS.items():
        op.alter_column("place", first, nullable=True)
        op.alter_column("place", second, nullable=True)
        op.create_check_constraint(
            op.f(f"ck_place_{name}"),
            "place",
            f"({first} IS NULL) = ({second} IS NULL)",
        )

    _seed_categories()


def downgrade() -> None:
    """Restore required place columns and the old category codes."""
    bind = op.get_bind()
    incomplete = bind.scalar(
        sa.text(
            "SELECT count(*) FROM place WHERE category_id IS NULL OR start_hour IS NULL"
        )
    )
    if incomplete:
        raise RuntimeError(
            f"{incomplete} place rows lack a category or hours; "
            "fill or delete them before downgrading"
        )
    for name, (first, second) in _PAIRS.items():
        op.drop_constraint(op.f(f"ck_place_{name}"), "place", type_="check")
        op.alter_column("place", first, nullable=False)
        op.alter_column("place", second, nullable=False)

    # Places on an added code keep the RESTRICT foreign key from failing here.
    op.execute(
        sa.text("DELETE FROM category WHERE code::text IN :codes").bindparams(
            sa.bindparam("codes", value=_ADDED_CODES, expanding=True)
        )
    )
    op.drop_constraint(op.f("uq_category_code"), "category", type_="unique")
    _swap_category_code(_OLD_CODES)
