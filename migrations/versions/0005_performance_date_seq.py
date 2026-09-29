"""Replace performance times with festival day, sequence and live flag.

Revision ID: 0005_performance_date_seq
Revises: 0004_place_sequence_unique

Existing rows keep their day and order. ``date`` is the ``start_at`` day in
Asia/Seoul, and ``seq`` numbers each day by ``start_at, id``. ``is_live``
starts as false.

Downgrade cannot recover the original times. It restores ``start_at`` and
``end_at`` as Seoul midnight of ``date`` plus ``seq - 1`` seconds, so the day
and order survive a downgrade and re-upgrade. ``is_live`` is dropped.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_performance_date_seq"
down_revision: str | Sequence[str] | None = "0004_place_sequence_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FESTIVAL_TIME_ZONE = "Asia/Seoul"


def upgrade() -> None:
    """Derive date and seq from start_at, then drop the time columns."""
    op.add_column("performance", sa.Column("date", sa.Date(), nullable=True))
    op.add_column("performance", sa.Column("seq", sa.Integer(), nullable=True))
    op.add_column(
        "performance",
        sa.Column("is_live", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute(
        sa.text(
            "UPDATE performance AS p SET date = r.day, seq = r.position "
            "FROM (SELECT id, day, row_number() OVER "
            "(PARTITION BY day ORDER BY start_at, id) AS position "
            "FROM (SELECT id, start_at, "
            "(start_at AT TIME ZONE :zone)::date AS day FROM performance) AS d"
            ") AS r WHERE p.id = r.id"
        ).bindparams(zone=_FESTIVAL_TIME_ZONE)
    )
    op.alter_column("performance", "date", nullable=False)
    op.alter_column("performance", "seq", nullable=False)

    op.drop_index(op.f("ix_performance_type_start_at_id"), table_name="performance")
    op.drop_index(op.f("ix_performance_start_at_id"), table_name="performance")
    op.drop_constraint(
        op.f("ck_performance_times_ordered"), "performance", type_="check"
    )
    op.drop_column("performance", "end_at")
    op.drop_column("performance", "start_at")

    op.create_check_constraint(
        op.f("ck_performance_seq_positive"), "performance", "seq >= 1"
    )
    op.create_unique_constraint(
        op.f("uq_performance_date_seq"),
        "performance",
        ["date", "seq"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        op.f("ix_performance_date_seq_id"), "performance", ["date", "seq", "id"]
    )
    op.create_index(
        op.f("ix_performance_type_date_seq_id"),
        "performance",
        ["type", "date", "seq", "id"],
    )


def downgrade() -> None:
    """Restore the time columns from date and seq. Original times are lost."""
    op.drop_index(op.f("ix_performance_type_date_seq_id"), table_name="performance")
    op.drop_index(op.f("ix_performance_date_seq_id"), table_name="performance")
    op.drop_constraint(op.f("uq_performance_date_seq"), "performance", type_="unique")
    op.drop_constraint(
        op.f("ck_performance_seq_positive"), "performance", type_="check"
    )

    for column in ("start_at", "end_at"):
        op.add_column(
            "performance",
            sa.Column(column, sa.DateTime(timezone=True), nullable=True),
        )
    op.execute(
        sa.text(
            "UPDATE performance SET start_at = "
            "(date + (seq - 1) * interval '1 second') AT TIME ZONE :zone, "
            "end_at = (date + (seq - 1) * interval '1 second') AT TIME ZONE :zone"
        ).bindparams(zone=_FESTIVAL_TIME_ZONE)
    )
    op.alter_column("performance", "start_at", nullable=False)
    op.alter_column("performance", "end_at", nullable=False)
    op.create_check_constraint(
        op.f("ck_performance_times_ordered"), "performance", "end_at >= start_at"
    )
    op.create_index(
        op.f("ix_performance_start_at_id"), "performance", ["start_at", "id"]
    )
    op.create_index(
        op.f("ix_performance_type_start_at_id"),
        "performance",
        ["type", "start_at", "id"],
    )

    op.drop_column("performance", "is_live")
    op.drop_column("performance", "seq")
    op.drop_column("performance", "date")
