import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.app import cors_origins_from_env, create_api_app
from customer.api.router import api_router
from quinquatria_persistence import Database


def create_app(database_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        url = (
            database_url if database_url is not None else os.environ.get("DATABASE_URL")
        )
        if not url:
            raise RuntimeError("DATABASE_URL is required")

        database = Database(url)
        application.state.database = database
        try:
            yield
        finally:
            await database.dispose()
            del application.state.database

    return create_api_app(
        title="Quinquatria Customer API",
        router=api_router,
        lifespan=lifespan,
        cors_origins=cors_origins_from_env,
    )


app = create_app()
