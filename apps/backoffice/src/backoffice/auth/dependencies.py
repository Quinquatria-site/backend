"""라우트가 주입받는 인증 관련 의존성."""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import BackgroundTasks, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backoffice.auth.tokens import invalid_token_error, verify_token
from backoffice.config import Settings, get_settings
from backoffice.images.s3 import S3ObjectStore
from backoffice.images.store import ObjectStore
from backoffice.revalidation.events import pop_tags

logger = logging.getLogger(__name__)

SettingsDep = Annotated[Settings, Depends(get_settings)]

_bearer = HTTPBearer(bearerFormat="JWT", auto_error=False)
"""OpenAPI에 Bearer 스키마를 선언해 Swagger UI의 Authorize로 토큰을 넣게 한다.

`auto_error`를 끄는 이유는 FastAPI 기본 오류 대신 명세 §4.3의 401을 내기 위해서다.
"""


def require_admin(
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """`Authorization: Bearer <token>`을 검증한다.

    헤더 누락과 토큰 검증 실패를 같은 401로 수렴시킨다.
    """
    token = "" if credentials is None else credentials.credentials.strip()
    if not token:
        raise invalid_token_error()

    verify_token(token, signing_key=settings.jwt_signing_key.get_secret_value())


def get_object_store(settings: SettingsDep) -> ObjectStore:
    """운영에서는 credential을 넘기지 않는다. workload IAM role을 쓴다."""
    return S3ObjectStore(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
    )


ObjectStoreDep = Annotated[ObjectStore, Depends(get_object_store)]


async def get_session(
    request: Request, background_tasks: BackgroundTasks
) -> AsyncIterator[AsyncSession]:
    """요청 하나가 transaction 하나를 연다."""
    async with request.app.state.database.transaction() as session:
        yield session

    # 위 context가 정상 종료된 뒤에만 이벤트를 꺼낸다. 이 시점에는 commit이
    # 끝났고 응답 전송은 아직 시작되지 않았다. background 작업에 session을 넘기지 않는다.
    for tag in pop_tags(session):
        try:
            sender = request.app.state.revalidation_sender
            if sender.enabled:
                background_tasks.add_task(sender.send_automatic, tag)
        except Exception:
            logger.warning(
                "ISR revalidation registration failed "
                "tag=%s kind=registration_error status=None",
                tag.value,
            )


# `function` scope로 라우트 반환 직후 transaction을 끝낸다. 기본 `request`
# scope는 응답 뒤에 commit하므로, commit이 실패해도 client는 이미 쓸 수 없는
# upload URL을 200으로 받은 뒤다.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
