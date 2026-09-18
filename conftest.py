"""저장소 루트 conftest — 이벤트 루프 선택과 패키지들이 공유하는 PostgreSQL 컨테이너.

psycopg는 async 모드에서 ProactorEventLoop 위를 돌 수 없는데, Windows의 asyncio
기본 이벤트 루프 정책이 만드는 것이 바로 ProactorEventLoop다. `packages/persistence`의
async 테스트가 실제 PostgreSQL 컨테이너에 psycopg async 드라이버로 접속하므로,
Windows에서는 selector 기반 루프를 쓰도록 pytest-asyncio에 알려줘야 한다.

컨테이너 픽스처를 여기 두는 이유는 `packages/persistence`와 `apps/backoffice`가
같은 DB를 써야 하기 때문이다. 패키지마다 따로 띄우면 테스트 시간이 배로 늘고,
Docker가 없을 때 실패 지점이 흩어진다.
"""

import asyncio
import selectors
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine
from testcontainers.community.postgres import PostgresContainer

if TYPE_CHECKING:
    from pytest import Config, Item

ROOT = Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def postgres_url():
    # Docker가 없으면 통합 테스트는 건너뛰지 않고 실패해야 한다.
    with PostgresContainer("postgres:18", driver="psycopg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def migrated_url(postgres_url):
    engine = create_engine(postgres_url)
    try:
        with engine.begin() as connection:
            config = AlembicConfig(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield postgres_url
    finally:
        engine.dispose()


def _selector_event_loop() -> asyncio.AbstractEventLoop:
    """psycopg async가 요구하는 selector 기반 이벤트 루프를 만든다.

    `WindowsSelectorEventLoopPolicy`는 Python 3.16에서 제거될 예정이라 쓰지
    않는다. 대신 루프 자체를 직접 만들어 넘긴다.
    """
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


if sys.platform == "win32":
    # Windows에서만 훅을 등록한다. pytest-asyncio는 이 훅이 등록돼 있으면
    # 매 테스트마다 반드시 non-empty mapping을 요구하므로(그렇지 않으면
    # pytest.UsageError), "다른 플랫폼은 기본 동작 유지"를 만족하려면 훅
    # 함수 자체를 다른 플랫폼에서 정의하지 않아야 한다 — 조건 분기 안에서
    # None을 반환하는 방식은 쓸 수 없다.
    def pytest_asyncio_loop_factories(
        config: "Config", item: "Item"
    ) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]] | None:
        """Windows에서 psycopg async 호환 루프를 pytest-asyncio에 알려준다."""
        return {"selector": _selector_event_loop}
