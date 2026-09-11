from typing import Annotated

from fastapi import APIRouter, Query

from common.query import NoQuery

router = APIRouter()


@router.get("/")
async def root(query: Annotated[NoQuery, Query()]) -> dict[str, str]:
    return {"message": "Hello World"}
