"""Festival entities and their translations.

Relationships must be loaded explicitly for use with async sessions. Database
foreign keys enforce deletion behavior even when a write bypasses the ORM.
"""

from __future__ import annotations

from datetime import date as DateValue
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import (
    CategoryCode,
    ImageContentType,
    ImageResourceType,
    ImageStatus,
    LanguageCode,
    NoticeType,
    PerformanceType,
)
from .geometry import Polygon, Vertex

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
_image_resource_type = SQLAlchemyEnum(
    ImageResourceType, name="image_resource_type", metadata=Base.metadata
)
_image_content_type = SQLAlchemyEnum(
    ImageContentType,
    name="image_content_type",
    metadata=Base.metadata,
    # 기본값은 멤버 이름("JPEG")을 저장한다. 명세가 다루는 값은 MIME
    # 문자열이므로 값을 저장하도록 바꾼다.
    values_callable=lambda enum_type: [member.value for member in enum_type],
)
_image_status = SQLAlchemyEnum(ImageStatus, name="image_status", metadata=Base.metadata)


class _IdentityMixin:
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)


class Image(_IdentityMixin, Base):
    """업로드된 S3 객체 하나의 수명 주기.

    `s3_key` unique가 명세 §4.6의 "하나의 object key는 하나의 기본
    리소스에서만 사용할 수 있다"를 DB 수준에서 강제한다.
    """

    __tablename__ = "image"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint(
            "declared_size BETWEEN 1 AND 10485760", name="declared_size_in_range"
        ),
        CheckConstraint(
            "byte_size IS NULL OR byte_size BETWEEN 1 AND 10485760",
            name="byte_size_in_range",
        ),
        # 상태와 해제 시각이 어긋나면 cleanup이 유예를 잘못 계산한다.
        CheckConstraint(
            "(detached_at IS NULL) = (status <> 'DETACHED')",
            name="detached_at_matches_status",
        ),
        Index(None, "status", "created_at"),
        Index(None, "status", "detached_at"),
    )

    s3_key: Mapped[str] = mapped_column(Text, unique=True)
    resource_type: Mapped[ImageResourceType] = mapped_column(_image_resource_type)
    content_type: Mapped[ImageContentType] = mapped_column(_image_content_type)
    declared_size: Mapped[int] = mapped_column(Integer)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[ImageStatus] = mapped_column(_image_status)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    detached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Category(_IdentityMixin, Base):
    __tablename__ = "category"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        # 배포 때 시드되는 고정 목록이라 코드마다 한 행이다 (명세 §5.3).
        UniqueConstraint("code"),
        Index(None, "code", "id"),
    )

    code: Mapped[CategoryCode] = mapped_column(_category_code_type)
    image_id: Mapped[int | None] = mapped_column(
        ForeignKey("image.id"), nullable=True, unique=True
    )

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
    """지도 위 장소. `is_polygon`이 위치 표현을 정한다.

    점 장소는 `x`, `y` 한 점이고, 구역 장소는 `area` 다각형(꼭짓점 3개 이상)이다.
    쓰지 않는 쪽은 NULL이다.
    """

    __tablename__ = "place"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("category_sequence >= 1", name="category_sequence_positive"),
        CheckConstraint("end_hour >= start_hour", name="hours_ordered"),
        # 좌표만 있는 장소를 허용하되 짝은 함께 비운다 (명세 §5.4).
        CheckConstraint(
            "(category_id IS NULL) = (category_sequence IS NULL)",
            name="category_paired",
        ),
        CheckConstraint(
            "(start_hour IS NULL) = (end_hour IS NULL)", name="hours_paired"
        ),
        # 점 장소는 x·y만, 구역 장소는 area만 쓴다 (명세 §5.4).
        CheckConstraint(
            "CASE WHEN is_polygon "
            "THEN area IS NOT NULL AND x IS NULL AND y IS NULL "
            "ELSE area IS NULL AND x IS NOT NULL AND y IS NOT NULL END",
            name="shape_matches",
        ),
        CheckConstraint("npoints(area) >= 3", name="area_vertices"),
        # 구역 번호(A1 …)가 두 장소에 붙지 않게 한다. 요청 하나가 한 행만 바꾸므로
        # `place_image`와 달리 지연하지 않는다 (명세 §5.4, §8).
        UniqueConstraint("category_id", "category_sequence"),
        Index(None, "category_id", "category_sequence", "id"),
    )

    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id", ondelete="RESTRICT")
    )
    category_sequence: Mapped[int | None] = mapped_column(Integer)
    # 기본값을 Python에도 둬야 flush 뒤 읽을 때 lazy load(async 불가)가 나지 않는다.
    is_polygon: Mapped[bool] = mapped_column(default=False, server_default=false())
    x: Mapped[float | None] = mapped_column(Double)
    y: Mapped[float | None] = mapped_column(Double)
    # 목록 안을 고쳐도 변경으로 추적하지 않는다. 새 목록을 통째로 대입한다.
    area: Mapped[list[Vertex] | None] = mapped_column(Polygon())
    start_hour: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_hour: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    category: Mapped[Category | None] = relationship(
        back_populates="places", lazy="raise"
    )
    translations: Mapped[list[PlaceTranslation]] = relationship(
        back_populates="place",
        cascade=_OWNED_CASCADE,
        passive_deletes=True,
        lazy="raise",
        order_by=lambda: (PlaceTranslation.language_code, PlaceTranslation.id),
    )
    images: Mapped[list[PlaceImage]] = relationship(
        back_populates="place",
        cascade=_OWNED_CASCADE,
        order_by="PlaceImage.seq",
        lazy="raise",
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


class PlaceImage(_IdentityMixin, Base):
    """장소와 이미지의 순서 있는 연결.

    `seq` unique를 deferrable로 두는 것은 `performance(date, seq)`와 같은
    이유다. 순서를 다시 매기는 중간 상태를 한 transaction 안에서 허용해야
    한다.
    """

    __tablename__ = "place_image"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        # 이름을 지정하지 않아야 naming convention(uq_place_image_place_id_seq)이
        # 적용된다. "uq" convention은 %(constraint_name)s 토큰이 없어, 이름을
        # 주면 그 값이 그대로 쓰여 마이그레이션의 제약 이름과 어긋난다.
        UniqueConstraint("place_id", "seq", deferrable=True, initially="DEFERRED"),
        Index(None, "place_id", "seq"),
    )

    place_id: Mapped[int] = mapped_column(ForeignKey("place.id", ondelete="CASCADE"))
    image_id: Mapped[int] = mapped_column(ForeignKey("image.id"), unique=True)
    seq: Mapped[int] = mapped_column(Integer)

    place: Mapped[Place] = relationship(back_populates="images", lazy="raise")


class Menu(_IdentityMixin, Base):
    __tablename__ = "menu"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("price >= 0", name="price_nonnegative"),
        Index(None, "place_id", "id"),
    )

    place_id: Mapped[int] = mapped_column(ForeignKey("place.id", ondelete="CASCADE"))
    image_id: Mapped[int | None] = mapped_column(
        ForeignKey("image.id"), nullable=True, unique=True
    )
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
    """축제 일차(`date`)와 그 안의 노출 순서(`seq`)로 배치되는 공연.

    `(date, seq)` unique는 deferrable이다. 재정렬이 한 transaction 안에서
    여러 행의 `seq`를 맞바꾸는 중간 상태를 허용해야 한다 (명세 §5.6).
    """

    __tablename__ = "performance"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        UniqueConstraint("date", "seq", deferrable=True, initially="DEFERRED"),
        Index(None, "date", "seq", "id"),
        Index(None, "type", "date", "seq", "id"),
    )

    type: Mapped[PerformanceType] = mapped_column(_performance_type)
    image_id: Mapped[int | None] = mapped_column(
        ForeignKey("image.id"), nullable=True, unique=True
    )
    date: Mapped[DateValue] = mapped_column(Date)
    seq: Mapped[int] = mapped_column(Integer)
    is_live: Mapped[bool] = mapped_column(server_default=false())

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
    images: Mapped[list[NoticeImage]] = relationship(
        back_populates="notice",
        cascade=_OWNED_CASCADE,
        order_by="NoticeImage.seq",
        lazy="raise",
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


class NoticeImage(_IdentityMixin, Base):
    """공지와 이미지의 순서 있는 연결. 제약은 `PlaceImage`와 같은 이유로 둔다."""

    __tablename__ = "notice_image"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        UniqueConstraint("notice_id", "seq", deferrable=True, initially="DEFERRED"),
        Index(None, "notice_id", "seq"),
    )

    notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id", ondelete="CASCADE"))
    image_id: Mapped[int] = mapped_column(ForeignKey("image.id"), unique=True)
    seq: Mapped[int] = mapped_column(Integer)

    notice: Mapped[Notice] = relationship(back_populates="images", lazy="raise")


class LostItem(_IdentityMixin, Base):
    __tablename__ = "lost_item"
    __table_args__ = (
        CheckConstraint("id > 0", name="id_positive"),
        Index(None, "created_at", "id"),
        Index(None, "is_returned", "created_at", "id"),
    )

    image_id: Mapped[int | None] = mapped_column(
        ForeignKey("image.id"), nullable=True, unique=True
    )
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
