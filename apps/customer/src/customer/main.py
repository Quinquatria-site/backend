from fastapi import FastAPI

from backend.packages.common.src.common.app import create_api_app
from customer.api.router import api_router


def create_app() -> FastAPI:
    return create_api_app(title="Quinquatria Customer API", router=api_router)


app = create_app()
