"""도메인 패키지의 라우터가 보호 라우터에 미리 등록되어 있다.

이슈별 PR이 `api/router.py`를 고치지 않고 자기 도메인 폴더만 바꾸도록 등록을
한곳에 고정한다. 인증 누락은 `test_authorization.py`의 라우트 열거가 잡는다.
"""

from backoffice.api.router import DOMAIN_ROUTERS
from backoffice.domains.catalog.routes import router as catalog
from backoffice.domains.lost_items.routes import router as lost_items
from backoffice.domains.notices.routes import router as notices
from backoffice.domains.performances.routes import router as performances


def test_every_domain_router_is_registered_once() -> None:
    assert DOMAIN_ROUTERS == (catalog, performances, notices, lost_items)
