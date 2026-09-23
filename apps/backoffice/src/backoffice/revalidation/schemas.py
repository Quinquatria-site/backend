"""백엔드와 프론트 수신기가 공유하는 재검증 식별 정보."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RevalidationTarget(StrEnum):
    PLACES = "PLACES"
    PERFORMANCES = "PERFORMANCES"
    NOTICES = "NOTICES"
    LOST_ITEMS = "LOST_ITEMS"


class ResourceType(StrEnum):
    CATEGORY = "CATEGORY"
    PLACE = "PLACE"
    MENU = "MENU"
    PERFORMANCE = "PERFORMANCE"
    NOTICE = "NOTICE"
    LOST_ITEM = "LOST_ITEM"


RESOURCE_TARGETS: dict[ResourceType, RevalidationTarget] = {
    ResourceType.CATEGORY: RevalidationTarget.PLACES,
    ResourceType.PLACE: RevalidationTarget.PLACES,
    ResourceType.MENU: RevalidationTarget.PLACES,
    ResourceType.PERFORMANCE: RevalidationTarget.PERFORMANCES,
    ResourceType.NOTICE: RevalidationTarget.NOTICES,
    ResourceType.LOST_ITEM: RevalidationTarget.LOST_ITEMS,
}


class RevalidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target: RevalidationTarget
    resource_type: ResourceType
    id: Annotated[int, Field(strict=True, gt=0)] | None = None

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if self.target != RESOURCE_TARGETS[self.resource_type]:
            raise ValueError("target과 resource_type의 조합이 올바르지 않습니다")
        return self


class RevalidationResponse(RevalidationRequest):
    accepted: Literal[True] = True
