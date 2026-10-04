"""Let a place be an area polygon instead of a single point.

Revision ID: 0008_place_polygon_area
Revises: 0007_notice_image

``is_polygon`` picks how a place is located. A point place keeps ``x`` and
``y`` and leaves ``area`` empty. A polygon place stores its outline in
``area`` with at least three vertices and leaves ``x`` and ``y`` empty.
``area`` uses the built-in ``polygon`` type, so no custom type is created.

Existing rows all become point places.

Downgrade fails while any polygon place exists.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_place_polygon_area"
down_revision: str | Sequence[str] | None = "0007_notice_image"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SHAPE_MATCHES = (
    "CASE WHEN is_polygon "
    "THEN area IS NOT NULL AND x IS NULL AND y IS NULL "
    "ELSE area IS NULL AND x IS NOT NULL AND y IS NOT NULL END"
)


def upgrade() -> None:
    op.add_column(
        "place",
        sa.Column(
            "is_polygon", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    # SQLAlchemy has no built-in polygon type, and a migration must not import
    # the application's type, so the column is added in plain SQL.
    op.execute("ALTER TABLE place ADD COLUMN area polygon")
    op.alter_column("place", "x", nullable=True)
    op.alter_column("place", "y", nullable=True)
    op.create_check_constraint(op.f("ck_place_shape_matches"), "place", _SHAPE_MATCHES)
    op.create_check_constraint(
        op.f("ck_place_area_vertices"), "place", "npoints(area) >= 3"
    )


def downgrade() -> None:
    polygons = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM place WHERE is_polygon")
    )
    if polygons:
        raise RuntimeError(
            f"{polygons} place row(s) are polygons. "
            "Convert or delete them before downgrading."
        )

    op.drop_constraint(op.f("ck_place_area_vertices"), "place", type_="check")
    op.drop_constraint(op.f("ck_place_shape_matches"), "place", type_="check")
    op.alter_column("place", "x", nullable=False)
    op.alter_column("place", "y", nullable=False)
    op.drop_column("place", "area")
    op.drop_column("place", "is_polygon")
