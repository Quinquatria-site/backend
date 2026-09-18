"""Backoffice 테스트가 공유하는 픽스처."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from backoffice.auth.dependencies import get_object_store, get_session
from backoffice.config import Settings, get_settings
from backoffice.main import create_app
from quinquatria_persistence import Database
from quinquatria_persistence.base import Base

from ._auth import ISSUANCE_CODE, SIGNING_KEY
from ._images import FakeObjectStore, recording_session


@pytest.fixture
def settings() -> Settings:
    """환경변수를 읽지 않고 명시값으로 만든 설정."""
    return Settings(
        issuance_code=SecretStr(ISSUANCE_CODE),
        jwt_signing_key=SecretStr(SIGNING_KEY),
<<<<<<< HEAD
        # `database_url`은 Customer와 공유하는 이름이라 alias로만 받는다.
        DATABASE_URL="postgresql+psycopg://unused-in-contract-tests/quinquatria",
=======
        database_url="postgresql+psycopg://unused-in-contract-tests/quinquatria",
>>>>>>> b6d87efd8ca25d827a2d005f9f426d401bb4dc32
        s3_bucket="test-bucket",
        s3_region="ap-northeast-2",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    return TestClient(application)


@pytest.fixture
def object_store() -> FakeObjectStore:
    return FakeObjectStore()


@pytest.fixture
def upload_client(settings: Settings, object_store: FakeObjectStore) -> TestClient:
    """DB 쓰기를 기록만 하는 세션으로 대신한 발급 전용 클라이언트."""
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_object_store] = lambda: object_store
    application.dependency_overrides[get_session] = recording_session
    return TestClient(application)


@pytest_asyncio.fixture
async def database(migrated_url) -> AsyncIterator[Database]:
    """이미지 테스트가 쓰는 DB. 매번 전체 테이블을 비운다."""
    instance = Database(migrated_url)
    tables = ", ".join(table.name for table in reversed(Base.metadata.sorted_tables))
    try:
        async with instance.engine.begin() as connection:
            await connection.execute(
                text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
            )
        yield instance
    finally:
        await instance.dispose()
