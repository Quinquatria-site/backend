from fastapi import FastAPI

from backoffice.api.router import api_router
from backend.packages.common.src.common.app import create_api_app


def create_app() -> FastAPI:
    return create_api_app(title="Quinquatria Backoffice API", router=api_router)


app = create_app()
