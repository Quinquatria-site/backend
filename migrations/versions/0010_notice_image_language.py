"""Give each notice language its own ordered images.

Revision ID: 0010_notice_image_language
Revises: 0009_category_additions

Images with text in them, such as promotion cards, differ by language, so
``notice_image`` gains ``language_code``. A composite foreign key to
``notice_translation(notice_id, language_code)`` keeps images to languages
that have a translation, removes them with it and follows a change of its
language. Order is now unique per
notice and language.

Existing images move to the KO translation, which every notice created through
the API has. Upgrade refuses notices that have images but no KO translation
rather than guessing a language; resolve those rows before running it.

Downgrade fails while any notice has images in a language other than KO,
because the old single list cannot tell languages apart.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_notice_image_language"
down_revision: str | Sequence[str] | None = "0009_category_additions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRANSLATION_FK = "fk_notice_image_notice_id_notice_translation"


def upgrade() -> None:
    bind = op.get_bind()
    orphaned = bind.scalar(
        sa.text(
            "SELECT count(DISTINCT i.notice_id) FROM notice_image AS i "
            "WHERE NOT EXISTS (SELECT 1 FROM notice_translation AS t "
            "WHERE t.notice_id = i.notice_id AND t.language_code = 'KO')"
        )
    )
    if orphaned:
        raise RuntimeError(
            f"{orphaned} notice(s) have images but no KO translation; "
            "add the translation or remove the images before upgrading"
        )

    op.add_column(
        "notice_image",
        sa.Column(
            "language_code",
            postgresql.ENUM(name="language_code", create_type=False),
            nullable=True,
        ),
    )
    op.execute("UPDATE notice_image SET language_code = 'KO'")
    op.alter_column("notice_image", "language_code", nullable=False)

    op.drop_index(op.f("ix_notice_image_notice_id_seq"), table_name="notice_image")
    op.drop_constraint(
        op.f("uq_notice_image_notice_id_seq"), "notice_image", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_notice_image_notice_id_language_code_seq"),
        "notice_image",
        ["notice_id", "language_code", "seq"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        op.f("ix_notice_image_notice_id_language_code_seq"),
        "notice_image",
        ["notice_id", "language_code", "seq"],
    )
    op.create_foreign_key(
        op.f(_TRANSLATION_FK),
        "notice_image",
        "notice_translation",
        ["notice_id", "language_code"],
        ["notice_id", "language_code"],
        ondelete="CASCADE",
        onupdate="CASCADE",
    )


def downgrade() -> None:
    bind = op.get_bind()
    localized = bind.scalar(
        sa.text(
            "SELECT count(DISTINCT notice_id) FROM notice_image "
            "WHERE language_code <> 'KO'"
        )
    )
    if localized:
        raise RuntimeError(
            f"{localized} notice(s) have images in a language other than KO; "
            "remove them before downgrading"
        )

    op.drop_constraint(op.f(_TRANSLATION_FK), "notice_image", type_="foreignkey")
    op.drop_index(
        op.f("ix_notice_image_notice_id_language_code_seq"),
        table_name="notice_image",
    )
    op.drop_constraint(
        op.f("uq_notice_image_notice_id_language_code_seq"),
        "notice_image",
        type_="unique",
    )
    op.drop_column("notice_image", "language_code")
    op.create_unique_constraint(
        op.f("uq_notice_image_notice_id_seq"),
        "notice_image",
        ["notice_id", "seq"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        op.f("ix_notice_image_notice_id_seq"), "notice_image", ["notice_id", "seq"]
    )
