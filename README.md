# Quinquatria Backend

Backoffice API와 Customer API를 함께 관리하는 FastAPI + uv 모노레포입니다.

## 구조

```text
apps/
├── backoffice/
│   ├── src/backoffice/
│   └── tests/
└── customer/
    ├── src/customer/
    └── tests/
packages/
└── persistence/
    ├── src/quinquatria_persistence/
    └── tests/
migrations/
└── versions/
```

각 앱은 독립적인 Python 패키지와 의존성 선언을 가지며, 저장소 루트의
`uv.lock`과 `.venv`를 공유합니다.
두 앱은 `quinquatria-persistence` workspace 패키지의 동일한 모델과
DB 세션을 사용합니다. 공통 패키지는 FastAPI에 의존하지 않습니다.

## 개발 환경

전체 워크스페이스를 동기화합니다.

```bash
uv sync --all-packages
```

개발 서버를 실행합니다.

```bash
uv --directory apps/backoffice run fastapi dev
uv --directory apps/customer run fastapi dev --port 8001
```

## 검사

PostgreSQL 통합 테스트는 실행 중인 Docker 호환 엔진이 필요합니다.
macOS에서 OrbStack을 사용한다면 먼저 `orb start`를 실행합니다.
Testcontainers가 `postgres:18` 이미지로 임시 컨테이너를 만들고 종료 후
제거합니다. 최초 실행에는 이미지 다운로드가 필요합니다. 테스트는 외부
`DATABASE_URL`을 사용하지 않으며 Docker가 없으면 실패합니다.

```bash
uv run --all-packages pytest
uv run ruff check .
uv run ruff format --check .
```

## 의존성 관리

의존성은 사용하는 앱에만 추가합니다. 예를 들어 backoffice 전용 인증
의존성은 다음과 같이 추가합니다.

```bash
uv add --package backoffice <package>
```

단일 개발 환경은 Python 패키지를 물리적으로 격리하지 않습니다. 배포 및
앱별 검증은 깨끗한 별도 환경에서 대상 패키지만 동기화합니다.

```bash
uv sync --package backoffice --no-dev --locked
uv sync --package customer --no-dev --locked
```

## PostgreSQL 스키마 관리

루트에서 `uv sync --all-packages --locked`를 실행하면 Alembic도 설치됩니다.
마이그레이션 실행 환경에 `DATABASE_URL`을 주입한 뒤 다음 명령을 실행합니다.
URL은 `postgresql+psycopg` 형식을 사용하며 `postgresql`과 `postgres` 형식도
동일한 드라이버로 처리합니다. 접속 정보는 Git에 저장하지 않습니다.

```bash
uv run --all-packages alembic upgrade head
uv run --all-packages alembic current
uv run --all-packages alembic check
```

마이그레이션은 Customer와 Backoffice가 공유하는 DB에 배포 단계에서 한 번
적용합니다. 앱 시작 시 `create_all`이나 자동 마이그레이션을 실행하지
않습니다. 최초 revision은 12개 테이블과 네 enum을 생성합니다.
`alembic downgrade base`는 이 테이블의 데이터까지 제거하므로 임시 DB에서
마이그레이션 왕복 검증을 할 때만 사용합니다.

스키마를 변경할 때는 모델과 함께 새 Alembic revision을 추가합니다.
기존 revision은 당시의 스키마를 보존하며 현재 모델에서 DDL을 재생성하지
않습니다. 통합 테스트는 `upgrade`, 재실행, `downgrade` 후 재적용과
모델 메타데이터의 일치를 검사합니다.

## 공통 세션과 트랜잭션

`Database(url)`은 앱별 엔진과 연결 풀을 소유합니다. 후속 API 구현에서 앱
시작 시 생성하고 종료 시 `await database.dispose()`를 호출합니다.
현재 기본 라우트는 DB 설정 없이 동작하며, 패키지 import도 접속을 만들지
않습니다.

```python
from quinquatria_persistence import (
    Database,
    LanguageCode,
    Notice,
    NoticeTranslation,
    NoticeType,
)


async def create_notice(database: Database) -> int:
    async with database.transaction() as session:
        notice = Notice(
            type=NoticeType.GENERAL,
            translations=[
                NoticeTranslation(
                    language_code=LanguageCode.KO,
                    title="축제 안내",
                    content="운영 시간을 확인해 주세요.",
                ),
            ],
        )
        session.add(notice)
        await session.flush()
        notice_id = notice.id
    # transaction 블록 종료 시 commit이 성공한 뒤 반환합니다.
    return notice_id
```

- `database.transaction()`은 정상 종료 시 commit, 예외 시 rollback하고
  세션을 닫습니다. 기본 리소스와 번역을 변경하는 함수에 이 세션을 그대로
  전달합니다. 하위 함수가 별도로 commit하거나 새 트랜잭션을 열면 안 됩니다.
- `database.session()`은 자동 commit하지 않습니다. 조회에 사용하며,
  commit하지 않은 변경은 블록 종료 시 rollback됩니다.
- 동시 작업마다 별도 세션을 사용합니다. `AsyncSession`을 서로 다른 task가
  공유하지 않습니다. commit 후 알림 같은 후속 작업은 트랜잭션 블록 밖에서
  수행합니다.
- ORM 관계는 암묵적 DB 조회를 막습니다. 필요한 관계는 `selectinload` 등으로
  명시적으로 조회합니다. 장소 이미지 배열은 순서와 ORM 내 변경을 추적합니다.

## DB 제약과 API 책임

DB는 필수값, 양수 ID, 허용 enum, 부모 FK, 언어별 번역 중복, 순서·가격·시간
범위를 보장합니다. 장소 이미지는 NULL 원소가 없는 비어 있지 않은 1차원
배열입니다. Place가 연결된 Category의 삭제는 거부하며, Place를 삭제하면
Menu와 관련 번역까지 연쇄 삭제합니다. 다른 리소스의 번역도 부모와 함께
삭제합니다. 이 규칙은 ORM을 거치지 않는 SQL에도 적용됩니다.

다음 규칙은 후속 API에서 검증합니다.

- 생성 시 KO 번역을 정확히 하나 포함하고 KO 번역의 개별 삭제를 금지합니다.
  이번 스키마에는 이를 강제하는 트리거가 없으므로 직접 SQL은 이 규칙을
  우회할 수 있습니다.
- 이미지 key의 배열 내 중복·리소스 간 독점 사용·실제 객체의 유효성을
  검사합니다.
- 입력 datetime의 UTC offset과 요청·응답 계약을 검사하고 DB 제약 위반을
  명세의 HTTP 오류로 변환합니다.

문서에 없는 문자열 길이·좌표 범위·카테고리 code 및 sequence 유일성은
제약으로 추가하지 않습니다. KO 생성 검증과 번역 변경은 기본 리소스와
같은 transaction에서 수행해야 합니다.
