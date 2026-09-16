"""Backoffice 테스트가 공유하는 픽스처."""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backoffice.config import Settings, get_settings
from backoffice.main import create_app

from ._auth import ISSUANCE_CODE, SIGNING_KEY


@pytest.fixture
def settings() -> Settings:
    """환경변수를 읽지 않고 명시값으로 만든 설정."""
    return Settings(
        issuance_code=SecretStr(ISSUANCE_CODE),
        jwt_signing_key=SecretStr(SIGNING_KEY),
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    return TestClient(application)
