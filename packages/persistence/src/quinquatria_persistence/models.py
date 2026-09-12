"""Festival entities and their translations.

Relationships must be loaded explicitly for use with async sessions. Database
foreign keys enforce deletion behavior even when a write bypasses the ORM.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import CategoryCode, LanguageCode, NoticeType, PerformanceType

_OWNED_CASCADE = "save-update, merge, delete, delete-orphan"
_language_code_type = SQLAlchemyEnum(
    LanguageCode, name="language_code", metadata=Base.metadata
)
_category_code_type = SQLAlchemyEnum(
    CategoryCode, name="category_code", metadata=Base.metadata
)
_performance_type = SQLAlchemyEnum(
    PerformanceType, name="performance_type", metadata=Base.metadata
)
_notice_type = SQLAlchemyEnum(NoticeType, name="notice_type", metadata=Base.metadata)


class _IdentityMixin:
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)


class Category(_IdentityMixin, Base):
    __tablename__ = "category"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        Index(None, "code", "id"),
    )

    code: Mapped[CategoryCode] = mapped_column(_category_code_type)
    category_icon_uri: Mapped[str | None] = mapped_column(Text, nullable=True)

    translations: Mapped[list[CategoryTranslation]] = relationship(
        back_populates="category",
        cascade=_OWNED_CASCADE,
        passive_deletes=True,
        lazy="raise",
        order_by=lambda: (CategoryTranslation.language_code, CategoryTranslation.id),
    )
    places: Mapped[list[Place]] = relationship(
        back_populates="category",
        passive_deletes="all",
        lazy="raise",
        order_by=lambda: (Place.category_sequence, Place.id),
    )


class CategoryTranslation(_IdentityMixin, Base):
    __tablename__ = "category_translation"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        UniqueConstraint("category_id", "language_code"),
    )

    category_id: Mapped[int] = mapped_column(
        ForeignKey("category.id", ondelete="CASCADE")
    )
    language_code: Mapped[LanguageCode] = mapped_column(_language_code_type)
    name: Mapped[str] = mapped_column(Text)

    category: Mapped[Category] = relationship(
        back_populates="translations", lazy="raise"
    )


class Place(_IdentityMixin, Base):
    __tablename__ = "place"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("category_sequence >= 1", name="category_sequence_positive"),
        CheckConstraint("end_hour >= start_hour", name="hours_ordered"),
        CheckConstraint(
            "place_image_uri IS NULL OR cardinality(place_image_uri) >= 1",
            name="images_nonempty",
        ),
        CheckConstraint(
            "place_image_uri IS NULL OR array_ndims(place_image_uri) = 1",
            name="images_one_dimensional",
        ),
        CheckConstraint(
            "place_image_uri IS NULL OR "
            "CASE WHEN array_ndims(place_image_uri) = 1 "
            "THEN array_position(place_image_uri, NULL) IS NULL ELSE false END",
            name="images_no_nulls",
        ),
        Index(None, "category_id", "category_sequence", "id"),
    )

    category_id: Mapped[int] = mapped_column(
        ForeignKey("category.id", ondelete="RESTRICT")
    )
    category_sequence: Mapped[int] = mapped_column(Integer)
    x: Mapped[float] = mapped_column(Double)
    y: Mapped[float] = mapped_column(Double)
    start_hour: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_hour: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    place_image_uri: Mapped[list[str] | None] = mapped_column(
        MutableList.as_mutable(ARRAY(Text)), nullable=True
    )

    category: Mapped[Category] = relationship(back_populates="places", lazy="raise")
    translations: Mapped[list[PlaceTranslation]] = relationship(
        back_populates="place",
        cascade=_OWNED_CASCADE,
        passive_deletes=True,
        lazy="raise",
        order_by=lambda: (PlaceTranslation.language_code, PlaceTranslation.id),
    )
    menus: Mapped[list[Menu]] = relationship(
        back_populates="place",
        cascade=_OWNED_CASCADE,
        passive_deletes=True,
        lazy="raise",
        order_by=lambda: Menu.id,
    )


class PlaceTranslation(_IdentityMixin, Base):
    __tablename__ = "place_translation"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        UniqueConstraint("place_id", "language_code"),
    )

    place_id: Mapped[int] = mapped_column(ForeignKey("place.id", ondelete="CASCADE"))
    language_code: Mapped[LanguageCode] = mapped_column(_language_code_type)
    name: Mapped[str] = mapped_column(Text)
    host_college: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))

    place: Mapped[Place] = relationship(back_populates="translations", lazy="raise")


class Menu(_IdentityMixin, Base):
    __tablename__ = "menu"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("price >= 0", name="price_nonnegative"),
        Index(None, "place_id", "id"),
    )

    place_id: Mapped[int] = mapped_column(ForeignKey("place.id", ondelete="CASCADE"))
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[int] = mapped_column(Integer)

    place: Mapped[Place] = relationship(back_populates="menus", lazy="raise")
    translations: Mapped[list[MenuTranslation]] = relationship(
        back_populates="menu",
        cascade=_OWNED_CASCADE,
        passive_deletes=True,
        lazy="raise",
        order_by=lambda: (MenuTranslation.language_code, MenuTranslation.id),
    )


class MenuTranslation(_IdentityMixin, Base):
    __tablename__ = "menu_translation"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        UniqueConstraint("menu_id", "language_code"),
    )

    menu_id: Mapped[int] = mapped_column(ForeignKey("menu.id", ondelete="CASCADE"))
    language_code: Mapped[LanguageCode] = mapped_column(_language_code_type)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))

    menu: Mapped[Menu] = relationship(back_populates="translations", lazy="raise")


class Performance(_IdentityMixin, Base):
    __tablename__ = "performance"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("end_at >= start_at", name="times_ordered"),
        Index(None, "start_at", "id"),
        Index(None, "type", "start_at", "id"),
    )

    type: Mapped[PerformanceType] = mapped_column(_performance_type)
    image_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    translations: Mapped[list[PerformanceTranslation]] = relationship(
        back_populates="performance",
        cascade=_OWNED_CASCADE,
        passive_deletes=True,
        lazy="raise",
        order_by=lambda: (
            PerformanceTranslation.language_code,
            PerformanceTranslation.id,
        ),
    )


class PerformanceTranslation(_IdentityMixin, Base):
    __tablename__ = "performance_translation"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        UniqueConstraint("performance_id", "language_code"),
    )

    performance_id: Mapped[int] = mapped_column(
        ForeignKey("performance.id", ondelete="CASCADE")
    )
    language_code: Mapped[LanguageCode] = mapped_column(_language_code_type)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))

    performance: Mapped[Performance] = relationship(
        back_populates="translations", lazy="raise"
    )


class Notice(_IdentityMixin, Base):
    __tablename__ = "notice"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        Index(None, "created_at", "id"),
        Index(None, "type", "created_at", "id"),
    )

    type: Mapped[NoticeType] = mapped_column(_notice_type)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )

    translations: Mapped[list[NoticeTranslation]] = relationship(
        back_populates="notice",
        cascade=_OWNED_CASCADE,
        passive_deletes=True,
        lazy="raise",
        order_by=lambda: (NoticeTranslation.language_code, NoticeTranslation.id),
    )


class NoticeTranslation(_IdentityMixin, Base):
    __tablename__ = "notice_translation"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        UniqueConstraint("notice_id", "language_code"),
    )

    notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id", ondelete="CASCADE"))
    language_code: Mapped[LanguageCode] = mapped_column(_language_code_type)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)

    notice: Mapped[Notice] = relationship(back_populates="translations", lazy="raise")


class LostItem(_IdentityMixin, Base):
    __tablename__ = "lost_item"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        Index(None, "created_at", "id"),
        Index(None, "is_returned", "created_at", "id"),
    )

    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_returned: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )

    translations: Mapped[list[LostItemTranslation]] = relationship(
        back_populates="lost_item",
        cascade=_OWNED_CASCADE,
        passive_deletes=True,
        lazy="raise",
        order_by=lambda: (LostItemTranslation.language_code, LostItemTranslation.id),
    )


class LostItemTranslation(_IdentityMixin, Base):
    __tablename__ = "lost_item_translation"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        UniqueConstraint("lost_item_id", "language_code"),
    )

    lost_item_id: Mapped[int] = mapped_column(
        ForeignKey("lost_item.id", ondelete="CASCADE")
    )
    language_code: Mapped[LanguageCode] = mapped_column(_language_code_type)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))
    found_location: Mapped[str] = mapped_column(Text, server_default=text("''"))

    lost_item: Mapped[LostItem] = relationship(
        back_populates="translations", lazy="raise"
    )
