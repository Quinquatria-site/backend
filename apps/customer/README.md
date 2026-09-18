# Customer API

Quinquatria 고객용 FastAPI 애플리케이션입니다. 인증 없이 카테고리와 장소,
장소에 속한 메뉴와 공연, 일반·상시 공지, 분실물을 조회합니다. 계약은
[API 명세](../../docs/API_SPEC.md) §2, §3.2, §3.3, §3.4, §3.5, §3.6을 따릅니다.

## 실행

저장소 루트에서 의존성을 설치합니다. DB 스키마 반영과 쓰기는 Backoffice가
담당합니다. Customer에는 Backoffice가 준비한 읽기 대상 DB의 `DATABASE_URL`을
주입한 뒤 개발 서버를 실행합니다. 접속 정보는 Git에 저장하지 않습니다.

```bash
uv sync --all-packages --locked
uv --directory apps/customer run fastapi dev --port 8001
```

Customer는 앱 시작 시 `DATABASE_URL`을 읽고 앱별 `Database`를 생성합니다.
값이 없거나 비어 있으면 시작에 실패합니다. Python에서 앱을 생성할 때는
`create_app(database_url=...)`로 명시적으로 주입할 수 있으며 이 값이
환경 변수보다 우선합니다.

모듈 import와 앱 팩토리 호출 시에는 설정을 읽거나 DB를 생성하지 않습니다.
DB 연결은 실제 조회 시 이루어집니다. 요청마다 독립적인 세션을 사용하고
종료 시 세션을 닫으며, 앱 종료 시 연결 풀을 해제합니다. 앱 시작 시
자동 마이그레이션이나 `create_all`은 실행하지 않습니다.

## 제공 경로

| Method | Path | 허용 query |
| --- | --- | --- |
| GET | `/api/v1/categories` | `language_code`, `page`, `size` |
| GET | `/api/v1/places` | `language_code`, `category_id`, `page`, `size` |
| GET | `/api/v1/places/{place_id}` | `language_code` |
| GET | `/api/v1/performances` | `language_code`, `type`, `date`, `page`, `size` |
| GET | `/api/v1/performances/{performance_id}` | `language_code` |
| GET | `/api/v1/notices` | `language_code`, `page`, `size` |
| GET | `/api/v1/notices/permanent` | `language_code`, `page`, `size` |
| GET | `/api/v1/notices/latest` | `language_code` |
| GET | `/api/v1/notices/{notice_id}` | `language_code` |
| GET | `/api/v1/lost-items` | `language_code`, `is_returned`, `page`, `size` |
| GET | `/api/v1/lost-items/{lost_item_id}` | `language_code` |

기존 `/api/v1/` 기본 응답도 유지합니다. 카탈로그 조회 API는 #8, 공연 조회
API는 #6, 공지 조회 API는 #10, 분실물 조회 API는 #13의 구현 범위입니다.
메뉴는 장소 상세의 `menus` 배열로 반환하며 별도의 메뉴 조회 경로는 없습니다.

- `language_code`는 `KO`(기본값), `EN`, `CHN`을 지원하며 대소문자를 구분합니다.
  선택한 번역만 기본 리소스 필드에 평탄화하고 다른 언어로 대체하지 않습니다.
- 목록에서 요청 언어 번역이 없는 항목은 제외합니다. 장소 목록은 장소 자체의
  번역으로 판단하며 부모 카테고리의 번역 유무에 영향을 받지 않습니다.
- 목록은 `items`, `page`, `size`, `total`을 반환합니다. 기본값은 `page=1`,
  `size=20`이며 `page >= 1`, `1 <= size <= 100`입니다. `total`은 번역과
  필터 적용 후 전체 개수이고, 범위를 벗어난 페이지는 빈 `items`를 반환합니다.
- 카테고리는 `id ASC`, 장소는 `category_id ASC, category_sequence ASC,
  id ASC`로 정렬합니다. `category_id`는 양수 ID이며 해당 카테고리에 조회할
  장소가 없으면 빈 목록을 반환합니다.
- 장소 상세는 목록 항목의 필드에 `menus`를 추가합니다. 메뉴는 `id ASC`로
  정렬하며 요청 언어 번역이 없는 메뉴만 제외합니다. 메뉴가 없으면 `[]`입니다.
- 이미지 필드는 저장된 S3 object key 또는 `null`을 반환합니다.
  `place_image_uri`의 순서를 보존하고 CloudFront URL을 조합하지 않습니다.
  이미지가 없는 장소는 빈 배열 대신 `null`을 반환합니다.
- 시각은 UTC offset이 포함된 ISO 8601 문자열입니다. DB 왕복 시 표기된
  offset은 바뀔 수 있으나 같은 시점을 나타냅니다. 번역의 `description`은
  항상 문자열이며 입력되지 않은 설명은 빈 문자열입니다.

### 공연

- `/performances`는 선택한 언어 번역이 있는 공연만
  `date ASC, seq ASC, id ASC`로 반환합니다. `type`은 `ARTIST`,
  `STUDENT`, `SPECIAL` 중 하나이며 `date`와 함께 선택적으로 필터링합니다.
- `date` query는 실제로 존재하는 달력 날짜의 `YYYY-MM-DD` 형식만
  허용합니다. 자릿수가 다른 날짜, datetime, UTC timestamp는
  `422 VALIDATION_ERROR`입니다.
- 요청 언어 번역과 `type`, `date` 필터를 적용한 뒤 `total`과 페이지를
  계산합니다. 번역이 없는 항목을 다른 언어로 대체하지 않습니다.
- `/performances/{performance_id}`는 요청 언어의 공연 단건을 반환합니다.
  기본 공연 행이 없으면 `RESOURCE_NOT_FOUND`, 공연은 있지만 요청 언어
  번역이 없으면 `TRANSLATION_NOT_FOUND`입니다.
- 응답의 `date`는 축제 일차, `seq`는 같은 일차 안의 노출 순서입니다.
  시작·종료 시각은 제공하지 않습니다. `is_live`는 저장된 값을 그대로
  반환하며 현재 시각으로 계산하지 않습니다.
- `image_uri`는 저장된 S3 object key 또는 `null`입니다. `description`은
  입력되지 않았을 때도 빈 문자열로 반환합니다.

이 브랜치는 Customer 조회만 제공합니다. 공연 생성·수정·삭제, 현재 공연 지정,
일차 내 순서 재정렬 같은 Backoffice 쓰기 API는 구현하지 않습니다.
실제 공연 조회는 Backoffice가 `date`, `seq`, `is_live` 열을 DB에 반영한 뒤에만
동작합니다. Customer는 이 스키마를 생성·변환하거나 데이터를 backfill하지
않습니다.

### 공지

- `/notices`는 `GENERAL` 공지만, `/notices/permanent`는 `PERMANENT`
  공지만 반환합니다. 임의의 `type` query는 받지 않습니다.
- 두 목록은 요청 언어 번역이 있는 공지만 `created_at DESC, id DESC`로
  정렬합니다. 번역과 공지 type을 적용한 뒤 `total`과 페이지를 계산합니다.
- `/notices/latest`는 번역 유무와 관계없이 전체 `GENERAL` 공지에서
  `created_at DESC, id DESC`의 첫 행을 먼저 확정합니다. 이 공지에 요청
  언어 번역이 없으면 이전 공지로 대체하지 않고
  `404 TRANSLATION_NOT_FOUND`를 반환합니다.
- `GENERAL` 공지가 하나도 없으면 `/notices/latest`는 본문과
  `Content-Type`이 없는 `204 No Content`를 반환합니다. `PERMANENT`
  공지는 최근 공지 후보에 포함하지 않습니다.
- `/notices/{notice_id}`는 일반·상시 공지를 모두 조회합니다. 기본 공지 행이
  없으면 `RESOURCE_NOT_FOUND`, 공지는 있지만 요청 언어 번역이 없으면
  `TRANSLATION_NOT_FOUND`입니다.

### 분실물

- `/lost-items`는 선택한 `language_code`의 번역이 있는 분실물만
  `created_at DESC, id DESC`로 반환합니다. `is_returned=true` 또는
  `is_returned=false`로 반환 여부를 선택해 조회할 수 있습니다.
- 요청 언어 번역과 `is_returned` 필터를 모두 적용한 뒤 `total`과 페이지를
  계산합니다. 번역이 없는 항목을 다른 언어로 대체하지 않습니다.
- `/lost-items/{lost_item_id}`는 요청 언어의 분실물 단건을 반환합니다.
  기본 분실물 행이 없으면 `RESOURCE_NOT_FOUND`, 분실물은 있지만 요청 언어
  번역이 없으면 `TRANSLATION_NOT_FOUND`입니다.
- `image_url`은 DB에 저장된 S3 object key를 그대로 반환하며 이미지가 없으면
  `null`입니다. CloudFront URL을 조합하지 않습니다.
- `description`과 `found_location`은 항상 문자열입니다. 저장된 값이
  없으면 `null` 대신 빈 문자열을 반환합니다.

## 오류

오류 본문은 공통 `code`, `message`, `details` 구조입니다.

| HTTP | code | 조건 |
| --- | --- | --- |
| 404 | `RESOURCE_NOT_FOUND` | 장소·공연·공지·분실물 ID에 해당하는 기본 리소스가 없음 |
| 404 | `TRANSLATION_NOT_FOUND` | 리소스는 있으나 요청 언어 번역이 없음 |
| 422 | `VALIDATION_ERROR` | 잘못된 ID·언어·페이지 값 또는 허용되지 않은 query |
| 500 | `INTERNAL_SERVER_ERROR` | 공개할 수 없는 내부 오류 |

장소 상세에 `page`, `size`, `category_id`를 전달하거나 카테고리 목록에
`code` 필터를 전달하면 `422`입니다. 공연 상세에 목록 query를 전달하거나
공연 목록에 명세에 없는 query를 전달해도 `422`입니다. 최근 공지와 공지
상세에 페이지 query를 전달하거나 공지 목록에 `type`을 전달해도 `422`입니다.
분실물 상세에 목록 query를 전달하거나 분실물 목록에 명세에 없는 필터를
전달해도 `422`입니다.

## 테스트

Customer 테스트는 `get_session` dependency를 mock `AsyncSession`으로
대체합니다. 실제 Database lifespan을 시작하지 않으므로 Docker,
PostgreSQL, `DATABASE_URL` 없이 실행됩니다.

```bash
uv run --all-packages pytest apps/customer/tests
uv run ruff check .
uv run ruff format --check .
```

HTTP 테스트는 mock 조회 결과의 응답 변환, `total`·페이지 초과,
장소·공연·공지·분실물/번역의 404 구분, 이미지 순서·`null`, query 허용 목록과
OpenAPI 계약을 검증합니다. 공연 HTTP 테스트는 type·date filter, 엄격한 날짜 형식,
저장된 `is_live`의 응답 변환을 함께 검증합니다. 공지 HTTP 테스트는
`GENERAL`·`PERMANENT` 목록 분리, 최신 기본 공지 우선 선택과 번역 fallback
금지, 본문과 `Content-Type`이 없는 `204 No Content` 응답을 검증합니다.
분실물 HTTP 테스트는 mock 조회 결과의 반환 여부, nullable 이미지 key,
`description`·`found_location`의 빈 문자열 변환을 함께 검증합니다.

번역 join·필터, count, pagination과 카탈로그 정렬 기준은 SQLAlchemy
statement를 PostgreSQL dialect로 compile한 SQL 구성으로 검사합니다. 공연은
type·date filter와 `date ASC, seq ASC, id ASC` 정렬 구성을 같은 방식으로
검사합니다. 공지는 type 구분과 `created_at DESC, id DESC` 정렬, 최신 `GENERAL`
기본 행을 먼저
고르는 query 구성을 같은 방식으로 검사합니다. 분실물은
`is_returned` 필터, 번역·필터 적용 후 count와 `created_at DESC, id DESC`
정렬 구성을 같은 방식으로 검사합니다. SQL을 DB에서 실행하지 않으므로 실제
`date`, `seq`, `is_live` 열의 존재, DB 제약과 런타임 query 실행은 Customer
테스트가 검증하지 않습니다.

별도 lifecycle 테스트는 startup 시점의 `DATABASE_URL` 선택, 앱별
`Database` 생성·해제, 동시 요청의 독립 세션과 정상·오류 요청의 세션 종료를
mock 경계에서 검증합니다. PostgreSQL의 스키마, 제약, migration과 실제
드라이버 실행은 `packages/persistence` 테스트 범위이며, 해당 테스트와 전체
워크스페이스 테스트는 Docker와 Testcontainers `postgres:18`이 필요합니다.
