"""Customer HTTP 테스트용 DB 경계 mock."""

from collections.abc import Mapping
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from customer.api.dependencies import get_session
from customer.main import create_app


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def execute_result():
    def factory(*rows: Mapping[str, object]) -> MagicMock:
        result = MagicMock()
        mappings = MagicMock()
        mappings.__iter__.side_effect = lambda: iter(rows)

        def one_or_none():
            if len(rows) > 1:
                raise AssertionError("one_or_none() received multiple mock rows")
            return rows[0] if rows else None

        mappings.one_or_none.side_effect = one_or_none
        result.mappings.return_value = mappings
        return result

    return factory


@pytest.fixture
def customer_client(mock_session):
    application = create_app()

    async def override_session():
        yield mock_session

    application.dependency_overrides[get_session] = override_session
    # Context manager를 사용하지 않아 실제 Database lifespan을 시작하지 않는다.
    client = TestClient(application)
    try:
        yield client
    finally:
        client.close()
        application.dependency_overrides.clear()


@pytest.fixture
def compiled_sql():
    def compile_statement(statement) -> str:
        compiled = statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
        return " ".join(str(compiled).split())

    return compile_statement
