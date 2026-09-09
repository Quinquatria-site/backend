# Quinquatria Backend

Backoffice API와 Customer API를 함께 관리하는 FastAPI + uv 모노레포입니다.

## 구조

```text
apps/
├── backoffice/
│   ├── src/backoffice/
│   └── tests/
├── common/
│   ├── src/common/
│   └── tests/
└── customer/
    ├── src/customer/
    └── tests/
```

각 앱은 독립적인 Python 패키지와 의존성 선언을 가지며, 저장소 루트의
`uv.lock`과 `.venv`를 공유합니다.

`common`은 배포되는 애플리케이션이 아니라 두 앱이 의존하는 라이브러리입니다.
[API 명세](docs/API_SPEC.md) §2의 공통 규칙 - `/api/v1` 경로, enum, 공통 검증,
페이지네이션, 오류 응답 - 을 구현하며 두 앱의 계약이 갈라지지 않게 합니다.
자세한 내용은 [apps/common/README.md](apps/common/README.md)를 참고합니다.

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
