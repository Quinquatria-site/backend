# Quinquatria API 명세서

| 항목              | 값                           |
| ----------------- | ---------------------------- |
| 문서 버전         | v0.1                         |
| 작성일            | 2026-09-09                   |
| 기준 문서         | [PRD](./PRD.md)              |
| 대상 애플리케이션 | Customer API, Backoffice API |
| API 버전          | v1                           |

## 1. 범위

이 문서는 PRD의 ERD를 기준으로 축제 정보 조회용 Customer API와 운영자용
Backoffice API의 HTTP 계약을 정의한다.

- Customer API는 인증 없이 축제 정보를 조회한다.
- Backoffice API는 발급 코드를 통해 받은 Bearer JWT로 데이터를 관리한다.
- 데이터 필드와 enum은 ERD를 우선한다.
- 일반 공지와 상시 공지는 서로 다른 Customer API로 조회하며, 가장 최근
  일반 공지 1건을 조회하는 API를 별도로 제공한다.
- Backoffice API가 S3 presigned PUT URL과 object key를 발급하며,
  이미지가 있는 기본 리소스는 업로드가 끝난 해당 key를 저장한다.

다음 기능은 이 API의 범위에 포함하지 않는다.

- 긴급 공지, `is_urgent`, 신규 공지 팝업, Short Polling
- ERD에 없는 별도 `ARTIST` 리소스
- 정적 축제 기본 정보와 축제 전반 타임라인
- 정적 편의시설 마커
- 이미지 binary를 FastAPI로 전달하는 multipart/form-data 프록시 업로드
- refresh token, access token 갱신, logout

## 2. 공통 규칙

### 2.1 Base URL

Customer API와 Backoffice API는 별도 FastAPI 애플리케이션으로 배포한다.
실제 origin은 환경별로 다르며 경로 규칙은 동일하다.

| API        | Base URL                     |
| ---------- | ---------------------------- |
| Customer   | `{customer_origin}/api/v1`   |
| Backoffice | `{backoffice_origin}/api/v1` |

### 2.2 HTTP와 JSON

- Backoffice와 Customer API 요청·응답의 기본 Content-Type은
  `application/json`이다. 클라이언트가 presigned URL로 S3에 직접 보내는
  PUT 요청은 이미지의 Content-Type을 사용한다.
- 필드 이름은 ERD와 동일한 `snake_case`를 사용한다.
- ID는 1 이상의 정수다.
- `datetime`은 UTC offset이 포함된 ISO 8601 문자열로 주고받는다.
  예: `2026-10-06T18:00:00+09:00`
- `price`는 원 단위의 0 이상 정수다.
- `x`와 `y`는 지도 좌표를 나타내는 실수다. 좌표계와 유효 범위는
  프론트엔드 지도 에셋 계약에서 별도로 정한다.
- 이미지 필드는 Backoffice 이미지 업로드 API가 반환한 S3 object key를
  저장하고 반환한다. 리소스 생성·수정 시 API가 객체 존재 여부, 용도별
  prefix, content type과 크기를 검증한다.
- 모든 이미지 필드는 선택이다. 이미지를 올리지 않은 리소스는 해당
  필드가 `null`이다. `POST`에서 생략하거나 `null`을 보낼 수 있고,
  `PATCH`에 `null`을 보내면 기존 이미지 연결을 해제한다.
- Customer 프론트엔드는 반환된 object key 앞에 환경별 CloudFront asset
  origin을 붙여 실제 이미지 URL을 만들며, `null`은 placeholder로
  처리한다.
- `place_image_uri` 배열의 순서는 화면 노출 순서이며 API가 보존한다.
  이미지가 없으면 빈 배열이 아니라 `null`이다.
- 번역의 `description`과 `found_location`은 선택이며 생략하면 빈
  문자열로 저장한다. 응답에는 항상 문자열로 포함하며 `null`이 아니다.
  나머지 번역 필드는 필수다.
- 응답 본문이 없는 `204 No Content`에는 Content-Type과 JSON 본문을
  포함하지 않는다.

### 2.3 Enum

| 이름               | 허용값                                          |
| ------------------ | ----------------------------------------------- |
| `language_code`    | `KO`, `EN`, `CHN`                               |
| `CATEGORY.code`    | `PUB`, `BOOTH`, `FOODTRUCK`, `MEDI`, `BRACELET` |
| `PERFORMANCE.type` | `ARTIST`, `STUDENT`, `SPECIAL`                  |
| `NOTICE.type`      | `PERMANENT`, `GENERAL`                          |

허용값은 대소문자를 구분한다. 다른 값은 `422 VALIDATION_ERROR`로
처리한다.

### 2.4 다국어

Customer API의 모든 조회 요청은 `language_code` query parameter를
지원하며 기본값은 `KO`다.

- 요청 언어의 번역만 기본 리소스에 평탄화하여 반환한다.
- 요청 언어 번역이 없는 리소스는 목록에서 제외한다.
- 단건 리소스에 요청 언어 번역이 없으면 기본 행이 존재하더라도
  `404 TRANSLATION_NOT_FOUND`를 반환한다.
- 장소 상세에 포함된 메뉴 중 요청 언어 번역이 없는 메뉴는 `menus`에서
  제외한다.
- 다른 언어로 자동 fallback하지 않는다.

Backoffice API는 선택 언어로 평탄화하지 않고 모든 번역을
`translations` 배열로 반환한다.

### 2.5 페이지네이션

모든 목록 API는 다음 query parameter를 사용한다.

| 이름   | 타입    | 필수   | 기본값 | 제약            |
| ------ | ------- | ------ | ------ | --------------- |
| `page` | integer | 아니요 | `1`    | 1 이상          |
| `size` | integer | 아니요 | `20`   | 1 이상 100 이하 |

목록 응답은 다음 형태로 통일한다.

```json
{
    "items": [],
    "page": 1,
    "size": 20,
    "total": 0
}
```

`total`은 번역과 필터 조건을 모두 적용한 뒤의 전체 개수다. `page`가
마지막 페이지를 초과하면 `200 OK`와 빈 `items`를 반환한다.

### 2.6 오류 응답

오류 응답은 다음 형태로 통일한다.

```json
{
    "code": "VALIDATION_ERROR",
    "message": "요청 값이 유효하지 않습니다.",
    "details": [
        {
            "field": "price",
            "reason": "0 이상의 정수여야 합니다."
        }
    ]
}
```

`details`는 추가 정보가 없으면 빈 배열이다. 내부 예외 메시지, SQL,
stack trace, 비밀값은 응답에 포함하지 않는다.

| HTTP 상태 | code                     | 사용 조건                                       |
| --------- | ------------------------ | ----------------------------------------------- |
| `400`     | `INVALID_REQUEST`        | JSON 구문 오류 또는 처리할 수 없는 요청         |
| `401`     | `INVALID_CREDENTIALS`    | 발급 코드 불일치                                |
| `401`     | `INVALID_TOKEN`          | 토큰 누락, 만료, 서명 또는 claim 검증 실패      |
| `404`     | `RESOURCE_NOT_FOUND`     | 경로 ID 또는 참조 대상 리소스가 없음            |
| `404`     | `TRANSLATION_NOT_FOUND`  | Customer 단건 조회의 요청 언어 번역이 없음      |
| `409`     | `DELETE_CONFLICT`        | 하위 리소스가 있어 삭제할 수 없음               |
| `409`     | `IMAGE_ALREADY_ATTACHED` | 다른 리소스가 사용 중인 이미지 key              |
| `413`     | `IMAGE_TOO_LARGE`        | URL 발급 요청의 `size`가 허용 크기를 초과함     |
| `422`     | `VALIDATION_ERROR`       | 타입, enum, 범위 또는 리소스 간 규칙 위반       |
| `422`     | `INVALID_IMAGE`          | 이미지 형식, key, prefix 또는 S3 객체 검증 실패 |
| `429`     | `RATE_LIMIT_EXCEEDED`    | 토큰 발급 요청 제한 초과                        |
| `500`     | `INTERNAL_SERVER_ERROR`  | 공개할 수 없는 서버 내부 오류                   |

## 3. Customer API

### 3.1 엔드포인트 요약

| Method | Path                                    | 지원 query parameter                           | 설명                     |
| ------ | --------------------------------------- | ---------------------------------------------- | ------------------------ |
| GET    | `/api/v1/categories`                    | `language_code`, `page`, `size`                | 카테고리 목록            |
| GET    | `/api/v1/places`                        | `language_code`, `category_id`, `page`, `size` | 장소 목록                |
| GET    | `/api/v1/places/{place_id}`             | `language_code`                                | 메뉴를 포함한 장소 상세  |
| GET    | `/api/v1/performances`                  | `language_code`, `type`, `page`, `size`        | 공연 목록                |
| GET    | `/api/v1/performances/{performance_id}` | `language_code`                                | 공연 상세                |
| GET    | `/api/v1/notices`                       | `language_code`, `page`, `size`                | 일반 공지 목록           |
| GET    | `/api/v1/notices/permanent`             | `language_code`, `page`, `size`                | 상시 공지 목록           |
| GET    | `/api/v1/notices/latest`                | `language_code`                                | 가장 최근 일반 공지 1건  |
| GET    | `/api/v1/notices/{notice_id}`           | `language_code`                                | 일반 또는 상시 공지 상세 |
| GET    | `/api/v1/lost-items`                    | `language_code`, `is_returned`, `page`, `size` | 분실물 목록              |
| GET    | `/api/v1/lost-items/{lost_item_id}`     | `language_code`                                | 분실물 상세              |

위 표의 지원 query parameter 목록은 전체 목록이다. 단건 조회는
`language_code`만 지원하며 `page`, `size`와 목록 filter를 받지 않는다.
표에 없는 query parameter를 전달하면 `422 VALIDATION_ERROR`를 반환한다.

FastAPI router에는 `/notices/permanent`와 `/notices/latest`를
`/notices/{notice_id}`보다 먼저 등록한다. 이를 통해 정적 경로가 동적
ID로 해석되는 것을 방지한다.

### 3.2 카테고리

#### GET `/api/v1/categories`

카테고리를 `id ASC`로 반환한다.

추가 query parameter는 `language_code`뿐이다.

Customer 카테고리 응답 필드는 다음과 같다.

| 필드                | 타입           | 설명                                                             |
| ------------------- | -------------- | ---------------------------------------------------------------- |
| `id`                | integer        | 카테고리 ID                                                      |
| `code`              | string enum    | 카테고리 코드                                                    |
| `category_icon_uri` | string \| null | `CATEGORY_ICON` 업로드로 받은 object key, 이미지가 없으면 `null` |
| `language_code`     | string enum    | 반환된 번역 언어                                                 |
| `name`              | string         | 번역된 카테고리명                                                |

응답 예시:

```json
{
    "items": [
        {
            "id": 1,
            "code": "PUB",
            "category_icon_uri": "images/category/550e8400-e29b-41d4-a716-446655440000.webp",
            "language_code": "KO",
            "name": "주점"
        }
    ],
    "page": 1,
    "size": 20,
    "total": 1
}
```

### 3.3 장소와 메뉴

#### GET `/api/v1/places`

| query           | 타입        | 필수   | 설명                        |
| --------------- | ----------- | ------ | --------------------------- |
| `language_code` | string enum | 아니요 | 기본값 `KO`                 |
| `category_id`   | integer     | 아니요 | 해당 카테고리의 장소만 조회 |

정렬은 `category_id ASC, category_sequence ASC, id ASC`다.

장소 목록 항목은 다음 필드를 반환한다.

| 필드                | 타입             | 설명                                                                |
| ------------------- | ---------------- | ------------------------------------------------------------------- |
| `id`                | integer          | 장소 ID                                                             |
| `category_id`       | integer          | 카테고리 ID                                                         |
| `category_sequence` | integer          | 카테고리 내 표시 순서                                               |
| `x`                 | number           | 지도 x 좌표                                                         |
| `y`                 | number           | 지도 y 좌표                                                         |
| `start_hour`        | datetime string  | 운영 시작 시각                                                      |
| `end_hour`          | datetime string  | 운영 종료 시각                                                      |
| `place_image_uri`   | string[] \| null | `PLACE_IMAGE` 업로드로 받은 object key 목록, 이미지가 없으면 `null` |
| `language_code`     | string enum      | 반환된 번역 언어                                                    |
| `name`              | string           | 장소명                                                              |
| `host_college`      | string           | 주최 단과대                                                         |
| `description`       | string           | 장소 또는 부스 설명                                                 |

#### GET `/api/v1/places/{place_id}`

| query           | 타입        | 필수   | 설명                          |
| --------------- | ----------- | ------ | ----------------------------- |
| `language_code` | string enum | 아니요 | 반환할 번역 언어, 기본값 `KO` |

목록 항목의 모든 필드와 `menus`를 반환한다. 메뉴는 `id ASC`로 정렬한다.

메뉴 항목의 필드는 다음과 같다.

| 필드            | 타입           | 설명                                                          |
| --------------- | -------------- | ------------------------------------------------------------- |
| `id`            | integer        | 메뉴 ID                                                       |
| `place_id`      | integer        | 장소 ID                                                       |
| `image_url`     | string \| null | `MENU_IMAGE` 업로드로 받은 object key, 이미지가 없으면 `null` |
| `price`         | integer        | 원 단위 가격                                                  |
| `language_code` | string enum    | 반환된 번역 언어                                              |
| `name`          | string         | 메뉴명                                                        |
| `description`   | string         | 메뉴 설명                                                     |

응답 예시:

```json
{
    "id": 10,
    "category_id": 1,
    "category_sequence": 3,
    "x": 127.42,
    "y": 36.18,
    "start_hour": "2026-10-06T10:00:00+09:00",
    "end_hour": "2026-10-06T22:00:00+09:00",
    "place_image_uri": [
        "images/place/550e8400-e29b-41d4-a716-446655440001.webp",
        "images/place/550e8400-e29b-41d4-a716-446655440002.webp"
    ],
    "language_code": "KO",
    "name": "글로벌캠퍼스 주점",
    "host_college": "통번역대학",
    "description": "음식과 음료를 판매합니다.",
    "menus": [
        {
            "id": 101,
            "place_id": 10,
            "image_url": "images/menu/550e8400-e29b-41d4-a716-446655440003.webp",
            "price": 5000,
            "language_code": "KO",
            "name": "떡볶이",
            "description": "매운 떡볶이"
        }
    ]
}
```

### 3.4 공연

#### GET `/api/v1/performances`

| query           | 타입        | 필수   | 설명           |
| --------------- | ----------- | ------ | -------------- |
| `language_code` | string enum | 아니요 | 기본값 `KO`    |
| `type`          | string enum | 아니요 | 공연 유형 필터 |

정렬은 `start_at ASC, id ASC`다. 현재 공연 여부는 API가 계산하지 않고
클라이언트가 `start_at`과 `end_at`으로 판별한다.

#### GET `/api/v1/performances/{performance_id}`

| query           | 타입        | 필수   | 설명                          |
| --------------- | ----------- | ------ | ----------------------------- |
| `language_code` | string enum | 아니요 | 반환할 번역 언어, 기본값 `KO` |

공연 단건을 반환한다.

공연 응답 필드는 다음과 같다.

| 필드            | 타입            | 설명                                                                 |
| --------------- | --------------- | -------------------------------------------------------------------- |
| `id`            | integer         | 공연 ID                                                              |
| `type`          | string enum     | `ARTIST`, `STUDENT` 또는 `SPECIAL`                                   |
| `image_uri`     | string \| null  | `PERFORMANCE_IMAGE` 업로드로 받은 object key, 이미지가 없으면 `null` |
| `start_at`      | datetime string | 공연 시작 시각                                                       |
| `end_at`        | datetime string | 공연 종료 시각                                                       |
| `language_code` | string enum     | 반환된 번역 언어                                                     |
| `title`         | string          | 공연 또는 팀명                                                       |
| `description`   | string          | 공연 설명                                                            |

### 3.5 공지

#### GET `/api/v1/notices`

`type=GENERAL`인 공지만 `created_at DESC, id DESC`로 반환한다. 임의의
`type` query parameter는 받지 않는다.

| query           | 타입        | 필수   | 설명        |
| --------------- | ----------- | ------ | ----------- |
| `language_code` | string enum | 아니요 | 기본값 `KO` |

#### GET `/api/v1/notices/permanent`

`type=PERMANENT`인 공지만 `created_at DESC, id DESC`로 반환한다. 응답은 다른
목록 API와 동일하게 페이지네이션한다.

| query           | 타입        | 필수   | 설명        |
| --------------- | ----------- | ------ | ----------- |
| `language_code` | string enum | 아니요 | 기본값 `KO` |

#### GET `/api/v1/notices/latest`

`type=GENERAL`인 공지 중 가장 최근 1건을 반환한다. 최근 공지는
`created_at DESC, id DESC`의 첫 번째 행으로 결정한다. 상시 공지는 조회
대상에 포함하지 않는다.

| query           | 타입        | 필수   | 설명        |
| --------------- | ----------- | ------ | ----------- |
| `language_code` | string enum | 아니요 | 기본값 `KO` |

이 API는 단건 객체를 반환하므로 `page`와 `size`를 받지 않는다.
일반 공지가 하나도 없으면 빈 본문의 `204 No Content`를 반환한다.
가장 최근 일반 공지는 있지만 요청 언어 번역이 없으면 이전 공지로
대체하지 않고 `404 TRANSLATION_NOT_FOUND`를 반환한다.

성공 응답 예시:

```json
{
    "id": 31,
    "type": "GENERAL",
    "created_at": "2026-10-05T13:00:00+09:00",
    "language_code": "KO",
    "title": "축제 운영 시간 안내",
    "content": "부스는 오전 10시부터 운영합니다."
}
```

#### GET `/api/v1/notices/{notice_id}`

| query           | 타입        | 필수   | 설명                          |
| --------------- | ----------- | ------ | ----------------------------- |
| `language_code` | string enum | 아니요 | 반환할 번역 언어, 기본값 `KO` |

일반 공지와 상시 공지를 모두 조회할 수 있다.

공지 응답 필드는 다음과 같다.

| 필드            | 타입            | 설명                       |
| --------------- | --------------- | -------------------------- |
| `id`            | integer         | 공지 ID                    |
| `type`          | string enum     | `PERMANENT` 또는 `GENERAL` |
| `created_at`    | datetime string | 서버가 기록한 생성 시각    |
| `language_code` | string enum     | 반환된 번역 언어           |
| `title`         | string          | 공지 제목                  |
| `content`       | string          | 공지 본문                  |

일반 공지 목록 응답 예시:

```json
{
    "items": [
        {
            "id": 31,
            "type": "GENERAL",
            "created_at": "2026-10-05T13:00:00+09:00",
            "language_code": "KO",
            "title": "축제 운영 시간 안내",
            "content": "부스는 오전 10시부터 운영합니다."
        }
    ],
    "page": 1,
    "size": 20,
    "total": 1
}
```

### 3.6 분실물

#### GET `/api/v1/lost-items`

| query           | 타입        | 필수   | 설명           |
| --------------- | ----------- | ------ | -------------- |
| `language_code` | string enum | 아니요 | 기본값 `KO`    |
| `is_returned`   | boolean     | 아니요 | 반환 여부 필터 |

정렬은 `created_at DESC, id DESC`다.

#### GET `/api/v1/lost-items/{lost_item_id}`

| query           | 타입        | 필수   | 설명                          |
| --------------- | ----------- | ------ | ----------------------------- |
| `language_code` | string enum | 아니요 | 반환할 번역 언어, 기본값 `KO` |

분실물 단건을 반환한다.

분실물 응답 필드는 다음과 같다.

| 필드             | 타입            | 설명                                                               |
| ---------------- | --------------- | ------------------------------------------------------------------ |
| `id`             | integer         | 분실물 ID                                                          |
| `image_url`      | string \| null  | `LOST_ITEM_IMAGE` 업로드로 받은 object key, 이미지가 없으면 `null` |
| `is_returned`    | boolean         | 소유자 반환 여부                                                   |
| `created_at`     | datetime string | 서버가 기록한 등록 시각                                            |
| `language_code`  | string enum     | 반환된 번역 언어                                                   |
| `title`          | string          | 분실물 제목                                                        |
| `description`    | string          | 분실물 설명                                                        |
| `found_location` | string          | 습득 장소                                                          |

## 4. Backoffice 인증과 이미지 업로드

### 4.1 토큰 발급

#### POST `/api/v1/auth/token`

이 엔드포인트만 Bearer 인증 없이 호출한다.

요청:

```json
{
    "issuance_code": "***"
}
```

| 필드            | 타입   | 필수 | 설명                         |
| --------------- | ------ | ---- | ---------------------------- |
| `issuance_code` | string | 예   | 서버에 설정된 공유 발급 코드 |

성공 응답: `200 OK`

```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.example",
    "token_type": "Bearer",
    "expires_in": 18000
}
```

토큰 응답에는 `Cache-Control: no-store`와 `Pragma: no-cache`를 포함한다.

발급 코드가 일치하지 않으면 `401 INVALID_CREDENTIALS`를 반환한다.
발급 코드의 길이, 일부 문자, 일치 여부 같은 추가 정보는 노출하지 않는다.

토큰 발급 요청은 신뢰하는 reverse proxy가 확정한 client IP를 기준으로
rolling 60초 동안 최대 5회 허용한다. 성공과 실패 요청을 모두 집계한다.
초과 시 `429 RATE_LIMIT_EXCEEDED`와 초 단위 `Retry-After` header를
반환한다.

### 4.2 JWT 계약

- 서명 알고리즘은 `HS256`만 허용하고 JWT header의 다른 `alg`는
  거부한다.
- JWT 서명 키는 발급 코드와 다른 256-bit 이상의 무작위 비밀값을
  사용한다.
- `exp`는 `iat + 18000`으로 설정한다.
- 매 발급마다 새로운 UUID `jti`를 만든다.
- access token만 발급하며 refresh token과 token rotation은 제공하지
  않는다.
- 만료 후에는 발급 코드를 다시 제출해야 한다.

JWT claim은 다음과 같다.

| claim | 값 또는 규칙                         |
| ----- | ------------------------------------ |
| `iss` | `quinquatria-backoffice`             |
| `aud` | `quinquatria-backoffice-api`         |
| `sub` | `admin`                              |
| `iat` | 발급 시각의 NumericDate              |
| `exp` | 발급 시각부터 5시간 뒤의 NumericDate |
| `jti` | 발급마다 생성한 UUID                 |

Backoffice API는 서명과 함께 `iss`, `aud`, `sub`, `iat`, `exp`,
`jti`를 모두 검증한다. 허용 알고리즘 고정과 issuer, audience 검증은
[JWT Best Current Practices](https://www.rfc-editor.org/rfc/rfc8725.html)를
따른다.

### 4.3 인증 헤더

토큰 발급을 제외한 모든 Backoffice API 요청은 다음 헤더가 필요하다.

```http
Authorization: Bearer <access_token>
```

헤더가 없거나 토큰 검증에 실패하면 `401 INVALID_TOKEN`을 반환하고
`WWW-Authenticate: Bearer`를 포함한다.

### 4.4 비밀값 관리

발급 코드와 JWT 서명 키는 서로 다른 AWS Secrets Manager 비밀값으로
관리하고 애플리케이션 실행 시점에 주입한다.

- 소스 코드, Git, 문서 예시, CloudFormation output, 일반 환경 로그에
  실제 값을 넣지 않는다.
- 애플리케이션 실행 역할에는 필요한 각 비밀값에 대한 최소 읽기 권한만
  부여한다.
- 발급 요청 본문과 토큰 원문은 access log와 application log에서
  마스킹한다.
- 발급 코드 비교는 timing 정보가 드러나지 않는 상수 시간 비교를
  사용한다.

Secrets Manager의 저장 시 암호화와 KMS 권한 원칙은
[AWS Secrets Manager 암호화 문서](https://docs.aws.amazon.com/secretsmanager/latest/userguide/security-encryption.html)를
참고한다.

### 4.5 이미지 업로드 URL 발급

#### POST `/api/v1/uploads/images/presigned-url`

Bearer 인증이 필요한 Backoffice 전용 API다. 업로드할 이미지의 용도,
Content-Type과 크기를 JSON으로 전달하면 서버가 5분 동안 유효한 S3
presigned PUT URL과 object key를 반환한다. 이미지 binary는 FastAPI를
거치지 않고 클라이언트에서 S3로 직접 전송한다.

요청:

```json
{
    "resource_type": "PLACE_IMAGE",
    "content_type": "image/webp",
    "size": 348210
}
```

| 필드            | 타입        | 필수 | 설명                        |
| --------------- | ----------- | ---- | --------------------------- |
| `resource_type` | string enum | 예   | 이미지가 사용될 리소스 필드 |
| `content_type`  | string enum | 예   | 업로드할 이미지의 MIME type |
| `size`          | integer     | 예   | byte 단위의 예상 파일 크기  |

`resource_type`과 object key prefix의 매핑은 다음과 같다.

| resource_type       | 사용할 리소스 필드           | object key prefix     |
| ------------------- | ---------------------------- | --------------------- |
| `CATEGORY_ICON`     | `CATEGORY.category_icon_uri` | `images/category/`    |
| `PLACE_IMAGE`       | `PLACE.place_image_uri[]`    | `images/place/`       |
| `MENU_IMAGE`        | `MENU.image_url`             | `images/menu/`        |
| `PERFORMANCE_IMAGE` | `PERFORMANCE.image_uri`      | `images/performance/` |
| `LOST_ITEM_IMAGE`   | `LOST_ITEM.image_url`        | `images/lost-item/`   |

URL 발급 제한:

- 허용 `content_type`은 `image/jpeg`, `image/png`, `image/webp`다.
- `size`는 1 byte 이상 10 MiB 이하다.
- 허용하지 않는 Content-Type은 `422 INVALID_IMAGE`다.
- `size`가 10 MiB를 초과하면 `413 IMAGE_TOO_LARGE`다.
- 원본 파일명은 받지 않는다. 서버가 UUID와 Content-Type에 대응하는
  확장자로 object key를 만들며 client가 key를 지정할 수 없다.
- URL은 `PutObject` 한 작업, 생성된 key와 요청 Content-Type에만
  사용할 수 있도록 AWS Signature Version 4로 서명한다.
- 기존 object key를 덮어쓰지 않도록 `If-None-Match: *`를 서명 대상
  header에 포함하고 bucket policy에서도 conditional write를 강제한다.

성공 응답: `200 OK`

```json
{
    "upload_url": "https://example-bucket.s3.ap-northeast-2.amazonaws.com/images/place/example.webp?X-Amz-Signature=%3Credacted%3E",
    "method": "PUT",
    "object_key": "images/place/550e8400-e29b-41d4-a716-446655440001.webp",
    "expires_in": 300,
    "required_headers": {
        "Content-Type": "image/webp",
        "If-None-Match": "*"
    }
}
```

`upload_url`은 만료 전까지 해당 key에 업로드 권한을 부여하므로 응답,
access log와 application log에서 query string을 마스킹한다. URL 발급에
실패하면 `500 INTERNAL_SERVER_ERROR`를 반환한다.

클라이언트는 응답의 method, URL과 header를 변경하지 않고 이미지
binary를 S3로 전송한다.

```http
PUT <upload_url>
Content-Type: image/webp
If-None-Match: *

<binary>
```

- 성공한 S3 PUT은 `200 OK`를 반환한다.
- URL이 만료됐거나 서명된 header와 실제 header가 다르면 S3가
  `403`을 반환한다. 클라이언트는 새 URL을 발급받아야 한다.
- 같은 key가 이미 존재하면 S3가 `412 Precondition Failed`를 반환한다.
  클라이언트는 새 URL과 key를 발급받아 다시 업로드한다.
- presigned URL의 실제 만료는 설정한 300초와 URL을 서명한 임시 IAM
  credential의 남은 수명 중 더 짧은 값이다.

S3 presigned PUT과 Content-Type 일치 규칙은
[AWS S3 presigned upload 문서](https://docs.aws.amazon.com/AmazonS3/latest/userguide/PresignedUrlUploadObject.html)를
따른다. `If-None-Match: *` 조건부 쓰기의 동작은
[AWS S3 conditional write 문서](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)를
따른다.

S3 bucket은 public access를 차단하고 CloudFront에서만 원본 객체를 읽을
수 있도록 구성한다. URL을 서명하는 애플리케이션에는 static AWS access
key를 넣지 않고 workload IAM role에 대상 prefix의 `s3:PutObject`
최소 권한을 부여한다. Backoffice origin에서 S3 PUT을 호출할 수 있도록
bucket CORS에는 허용 origin, `PUT`, `Content-Type`,
`If-None-Match`만 명시한다.

### 4.6 이미지 연결과 수명 주기

모든 이미지 필드는 선택이므로 이 흐름은 이미지를 올릴 때만 수행한다.
이미지 없이 리소스를 만들려면 이미지 필드를 생략하거나 `null`로 보내고
바로 `POST`한다. 이미지는 나중에 `PATCH`로 연결할 수 있다.

이미지를 올리는 리소스의 생성·수정 흐름은 다음과 같다.

1. 필요한 이미지마다 `POST /api/v1/uploads/images/presigned-url`을
   호출한다.
2. 반환된 presigned URL과 필수 header로 이미지 binary를 S3에
   `PUT`한다.
3. S3 업로드가 성공하면 반환받았던 `object_key`를 기본 리소스의 이미지
   필드에 넣어 `POST` 또는 `PATCH`한다.
4. 리소스 API는 S3 객체가 존재하고 field에 맞는 prefix를 가지는지
   `HeadObject`로 확인한다. 실제 크기와 Content-Type을 다시 확인하고
   필요한 최소 byte range를 읽어 이미지 signature도 검증한다.
5. 검증과 DB transaction이 성공하면 저장된 object key를 포함한
   기본 리소스를 반환한다.

`PLACE.place_image_uri`의 이미지가 여러 개면 파일마다 업로드 API를
호출하고 반환된 key들을 노출 순서대로 배열에 넣는다. 배열을 보낼 때는
서로 다른 key를 1개 이상 포함해야 한다. 이미지가 없는 장소는 빈 배열이
아니라 `null`로 표현한다.

`PATCH`에 이미지 필드로 `null`을 보내면 기존 연결을 해제한다. 해제된
object key는 참조가 제거된 객체로 보고 아래 수명 주기 규칙을 따른다.

하나의 object key는 하나의 기본 리소스에서만 사용할 수 있다.

- 다른 리소스에 이미 연결된 key는 `409 IMAGE_ALREADY_ATTACHED`다.
- 같은 `place_image_uri` 배열에 key가 중복되면
  `422 INVALID_IMAGE`다.
- field와 key prefix가 맞지 않거나 객체가 없으면
  `422 INVALID_IMAGE`다.
- 실제 크기가 10 MiB를 초과하거나 발급 요청의 Content-Type과 이미지
  signature가 일치하지 않으면 `422 INVALID_IMAGE`다. 이 검증은
  URL 발급 요청의 `size`와 `content_type`만 신뢰하지 않는다.
- 현재 리소스가 이미 사용하는 key를 변경 없이 다시 보내는 것은
  허용한다.

이미지 객체는 immutable하게 다룬다. 이미지를 변경할 때 기존 key를
덮어쓰지 않고 새 파일을 업로드해 새 key로 `PATCH`한다.

- 리소스에 연결되지 않은 업로드 객체는 24시간 뒤 정리한다.
- `PATCH`로 교체되거나 기본 리소스 `DELETE`로 참조가 제거된 객체는 DB
  commit과 ISR 요청 이후 최소 24시간의 유예를 두고 비동기로 삭제한다.
- S3 삭제 실패는 이미 성공한 DB transaction을 rollback하지 않는다.
  실패를 기록하고 cleanup 작업에서 재시도한다.

## 5. Backoffice 리소스 API

### 5.1 공통 CRUD

아래 리소스에 동일한 CRUD 경로를 제공한다.

| 리소스      | collection path        |
| ----------- | ---------------------- |
| Category    | `/api/v1/categories`   |
| Place       | `/api/v1/places`       |
| Menu        | `/api/v1/menus`        |
| Performance | `/api/v1/performances` |
| Notice      | `/api/v1/notices`      |
| LostItem    | `/api/v1/lost-items`   |

각 collection path의 공통 동작은 다음과 같다.

| Method | Path                                            | 성공 상태 | 동작                              |
| ------ | ----------------------------------------------- | --------- | --------------------------------- |
| GET    | `/{resource}`                                   | `200`     | 페이지네이션 목록                 |
| GET    | `/{resource}/{id}`                              | `200`     | 단건 조회                         |
| POST   | `/{resource}`                                   | `201`     | 생성 후 생성된 리소스 반환        |
| PATCH  | `/{resource}/{id}`                              | `200`     | 전달된 필드만 수정 후 리소스 반환 |
| DELETE | `/{resource}/{id}`                              | `204`     | 영구 삭제                         |
| DELETE | `/{resource}/{id}/translations/{language_code}` | `204`     | 선택 언어 번역 삭제               |

Backoffice 목록은 번역 유무와 관계없이 기본 리소스를 반환한다.
`translations`는 `language_code ASC, id ASC`로 정렬한다.

Backoffice의 `GET /{resource}/{id}` 단건 조회는 query parameter를 받지
않는다. `language_code`도 지원하지 않으며 항상 모든 `translations`를
반환한다. query parameter를 전달하면 `422 VALIDATION_ERROR`다.

목록 필터와 정렬은 다음과 같다.

| 리소스      | 추가 query filter | 정렬                                             |
| ----------- | ----------------- | ------------------------------------------------ |
| Category    | `code`            | `id ASC`                                         |
| Place       | `category_id`     | `category_id ASC, category_sequence ASC, id ASC` |
| Menu        | `place_id`        | `place_id ASC, id ASC`                           |
| Performance | `type`            | `start_at ASC, id ASC`                           |
| Notice      | `type`            | `created_at DESC, id DESC`                       |
| LostItem    | `is_returned`     | `created_at DESC, id DESC`                       |

### 5.2 생성과 수정 규칙

- `POST` 요청에는 서버가 생성하는 기본 리소스 `id`, 번역 `id`,
  번역 FK, `created_at`을 포함하지 않는다.
- 모든 `POST` 요청은 `translations` 배열을 필수로 포함해야 하며,
  `language_code=KO` 번역이 정확히 1개 있어야 한다.
- `EN`과 `CHN` 번역은 선택 사항이다.
- 하나의 `translations` 요청 배열에 같은 `language_code`를 두 번
  포함하면 `422 VALIDATION_ERROR`다.
- `PATCH`의 모든 필드는 선택 사항이다. 수정할 필드가 하나도 없으면
  `422 VALIDATION_ERROR`다.
- `PATCH`에서 `translations`를 생략하면 기존 번역을 유지한다.
- `PATCH`에서 `translations`를 전달하면 각 항목의 `language_code`를
  기준으로 해당 번역만 upsert한다. 기존 언어는 update하고, 없는 언어는
  insert하며, 전달하지 않은 언어는 변경하지 않는다.
- `PATCH`의 `translations`에는 `KO`를 다시 보낼 필요가 없다. 예를 들어
  `EN`만 전달하면 기존 `KO`와 `CHN` 번역은 그대로 유지한다.
- upsert할 번역 항목은 해당 Translation 스키마의 필수 번역 필드를 모두
  포함해야 한다. 기존 번역의 `id`와 FK는 유지한다.
- 번역 항목의 `description`과 `found_location`은 선택이다. 번역 항목은
  전체 교체로 처리하므로, 이 필드를 생략하면 insert와 update 모두 빈
  문자열로 저장한다. 기존 값을 유지하려면 다시 보내야 한다.
- 빈 `translations` 배열은 실제 변경이 없으므로
  `422 VALIDATION_ERROR`다.
- 응답의 `translations` 배열은 `language_code` 오름차순, 같은 언어 안에서
  번역 `id` 오름차순으로 정렬한다. `language_code`의 순서는 `CHN`, `EN`,
  `KO`다.
- 기본 리소스 수정과 번역 upsert는 하나의 DB transaction으로
  처리한다.
- 번역 생성과 수정은 기본 리소스의 `PATCH`로만 처리한다. 번역 삭제는
  별도 `DELETE` 엔드포인트로 처리한다.
- ERD에 `updated_at` 또는 version 필드가 없으므로 동시 수정은
  last-write-wins로 처리한다.

예를 들어 다음 요청은 영어 번역만 update 또는 insert하고 기존 `KO`와
`CHN` 번역은 변경하지 않는다.

```http
PATCH /api/v1/notices/42
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
    "translations": [
        {
            "language_code": "EN",
            "title": "Updated Safety Guidelines",
            "content": "Please follow the updated safety instructions."
        }
    ]
}
```

번역 삭제 경로는 다음과 같다.

| 리소스                 | Path                                                                 |
| ---------------------- | -------------------------------------------------------------------- |
| CategoryTranslation    | `/api/v1/categories/{category_id}/translations/{language_code}`      |
| PlaceTranslation       | `/api/v1/places/{place_id}/translations/{language_code}`             |
| MenuTranslation        | `/api/v1/menus/{menu_id}/translations/{language_code}`               |
| PerformanceTranslation | `/api/v1/performances/{performance_id}/translations/{language_code}` |
| NoticeTranslation      | `/api/v1/notices/{notice_id}/translations/{language_code}`           |
| LostItemTranslation    | `/api/v1/lost-items/{lost_item_id}/translations/{language_code}`     |

`EN`과 `CHN` 번역은 삭제할 수 있다. `KO`는 모든 기본 리소스에 필요한
번역이므로 삭제 요청에 `409 DELETE_CONFLICT`를 반환한다. 기본 리소스나
요청 언어 번역이 없으면 `404 RESOURCE_NOT_FOUND`를 반환한다. 삭제
성공 시 빈 본문의 `204 No Content`를 반환한다.

### 5.3 Category 스키마

기본 리소스:

| 필드                | 타입                  | POST          | PATCH               | 설명                         |
| ------------------- | --------------------- | ------------- | ------------------- | ---------------------------- |
| `id`                | integer               | 서버 생성     | 수정 불가           | 카테고리 ID                  |
| `code`              | string enum           | 필수          | 선택                | 카테고리 코드                |
| `category_icon_uri` | string \| null        | 선택          | 선택                | 아이콘 S3 key, 기본값 `null` |
| `translations`      | CategoryTranslation[] | 필수, KO 포함 | 선택, 언어별 upsert | 전체 번역                    |

`CategoryTranslation`:

| 필드            | 타입        | 요청        | 응답 | 설명        |
| --------------- | ----------- | ----------- | ---- | ----------- |
| `id`            | integer     | 보내지 않음 | 포함 | 번역 ID     |
| `category_id`   | integer     | 보내지 않음 | 포함 | 카테고리 ID |
| `language_code` | string enum | 필수        | 포함 | 번역 언어   |
| `name`          | string      | 필수        | 포함 | 카테고리명  |

### 5.4 Place 스키마

기본 리소스:

| 필드                | 타입               | POST          | PATCH               | 설명                                       |
| ------------------- | ------------------ | ------------- | ------------------- | ------------------------------------------ |
| `id`                | integer            | 서버 생성     | 수정 불가           | 장소 ID                                    |
| `category_id`       | integer            | 필수          | 선택                | 존재하는 카테고리 ID                       |
| `category_sequence` | integer            | 필수          | 선택                | 1 이상의 카테고리 내 순서                  |
| `x`                 | number             | 필수          | 선택                | 지도 x 좌표                                |
| `y`                 | number             | 필수          | 선택                | 지도 y 좌표                                |
| `start_hour`        | datetime string    | 필수          | 선택                | 운영 시작 시각                             |
| `end_hour`          | datetime string    | 필수          | 선택                | 운영 종료 시각                             |
| `place_image_uri`   | string[] \| null   | 선택          | 선택                | 순서가 보존되는 이미지 목록, 기본값 `null` |
| `translations`      | PlaceTranslation[] | 필수, KO 포함 | 선택, 언어별 upsert | 전체 번역                                  |

`end_hour`가 `start_hour`보다 이르면 `422 VALIDATION_ERROR`다. 두 값이
같은 것은 허용한다. 존재하지 않는 `category_id`는
`404 RESOURCE_NOT_FOUND`다. `category_sequence`가 1 미만이면
`422 VALIDATION_ERROR`다.

`place_image_uri`는 이미지가 없음을 `null`로 표현한다. 배열을 보낼
때는 다음을 지킨다. 위반은 `422 VALIDATION_ERROR`다.

- 빈 배열 `[]`은 허용하지 않는다. 이미지가 없으면 `null`을 보낸다.
- 배열 원소는 `null`일 수 없다.
- 중첩 배열은 허용하지 않는다. 1차원 문자열 배열만 받는다.

`PlaceTranslation`:

| 필드            | 타입        | 요청        | 응답 | 설명                                   |
| --------------- | ----------- | ----------- | ---- | -------------------------------------- |
| `id`            | integer     | 보내지 않음 | 포함 | 번역 ID                                |
| `place_id`      | integer     | 보내지 않음 | 포함 | 장소 ID                                |
| `language_code` | string enum | 필수        | 포함 | 번역 언어                              |
| `name`          | string      | 필수        | 포함 | 장소명                                 |
| `host_college`  | string      | 필수        | 포함 | 주최 단과대                            |
| `description`   | string      | 선택        | 포함 | 장소 또는 부스 설명, 생략 시 빈 문자열 |

생성 요청 예시:

```json
{
    "category_id": 1,
    "category_sequence": 3,
    "x": 127.42,
    "y": 36.18,
    "start_hour": "2026-10-06T10:00:00+09:00",
    "end_hour": "2026-10-06T22:00:00+09:00",
    "place_image_uri": ["places/10/front.webp"],
    "translations": [
        {
            "language_code": "KO",
            "name": "글로벌캠퍼스 주점",
            "host_college": "통번역대학",
            "description": "음식과 음료를 판매합니다."
        },
        {
            "language_code": "EN",
            "name": "Global Campus Pub",
            "host_college": "College of Interpretation and Translation",
            "description": "Food and beverages are available."
        }
    ]
}
```

### 5.5 Menu 스키마

기본 리소스:

| 필드           | 타입              | POST          | PATCH               | 설명                              |
| -------------- | ----------------- | ------------- | ------------------- | --------------------------------- |
| `id`           | integer           | 서버 생성     | 수정 불가           | 메뉴 ID                           |
| `place_id`     | integer           | 필수          | 선택                | 존재하는 장소 ID                  |
| `image_url`    | string \| null    | 선택          | 선택                | 메뉴 이미지 S3 key, 기본값 `null` |
| `price`        | integer           | 필수          | 선택                | 원 단위의 0 이상 가격             |
| `translations` | MenuTranslation[] | 필수, KO 포함 | 선택, 언어별 upsert | 전체 번역                         |

존재하지 않는 `place_id`는 `404 RESOURCE_NOT_FOUND`다.

`MenuTranslation`:

| 필드            | 타입        | 요청        | 응답 | 설명                         |
| --------------- | ----------- | ----------- | ---- | ---------------------------- |
| `id`            | integer     | 보내지 않음 | 포함 | 번역 ID                      |
| `menu_id`       | integer     | 보내지 않음 | 포함 | 메뉴 ID                      |
| `language_code` | string enum | 필수        | 포함 | 번역 언어                    |
| `name`          | string      | 필수        | 포함 | 메뉴명                       |
| `description`   | string      | 선택        | 포함 | 메뉴 설명, 생략 시 빈 문자열 |

### 5.6 Performance 스키마

기본 리소스:

| 필드           | 타입                     | POST          | PATCH               | 설명                         |
| -------------- | ------------------------ | ------------- | ------------------- | ---------------------------- |
| `id`           | integer                  | 서버 생성     | 수정 불가           | 공연 ID                      |
| `type`         | string enum              | 필수          | 선택                | 공연 유형                    |
| `image_uri`    | string \| null           | 선택          | 선택                | 이미지 S3 key, 기본값 `null` |
| `start_at`     | datetime string          | 필수          | 선택                | 공연 시작 시각               |
| `end_at`       | datetime string          | 필수          | 선택                | 공연 종료 시각               |
| `translations` | PerformanceTranslation[] | 필수, KO 포함 | 선택, 언어별 upsert | 전체 번역                    |

`end_at`이 `start_at`보다 이르면 `422 VALIDATION_ERROR`다. 두 값이 같은
것은 허용한다.

`PerformanceTranslation`:

| 필드             | 타입        | 요청        | 응답 | 설명                         |
| ---------------- | ----------- | ----------- | ---- | ---------------------------- |
| `id`             | integer     | 보내지 않음 | 포함 | 번역 ID                      |
| `performance_id` | integer     | 보내지 않음 | 포함 | 공연 ID                      |
| `language_code`  | string enum | 필수        | 포함 | 번역 언어                    |
| `title`          | string      | 필수        | 포함 | 공연 또는 팀명               |
| `description`    | string      | 선택        | 포함 | 공연 설명, 생략 시 빈 문자열 |

### 5.7 Notice 스키마

기본 리소스:

| 필드           | 타입                | POST          | PATCH               | 설명                       |
| -------------- | ------------------- | ------------- | ------------------- | -------------------------- |
| `id`           | integer             | 서버 생성     | 수정 불가           | 공지 ID                    |
| `type`         | string enum         | 필수          | 선택                | `PERMANENT` 또는 `GENERAL` |
| `created_at`   | datetime string     | 서버 생성     | 수정 불가           | 생성 시각                  |
| `translations` | NoticeTranslation[] | 필수, KO 포함 | 선택, 언어별 upsert | 전체 번역                  |

`NoticeTranslation`:

| 필드            | 타입        | 요청        | 응답 | 설명      |
| --------------- | ----------- | ----------- | ---- | --------- |
| `id`            | integer     | 보내지 않음 | 포함 | 번역 ID   |
| `notice_id`     | integer     | 보내지 않음 | 포함 | 공지 ID   |
| `language_code` | string enum | 필수        | 포함 | 번역 언어 |
| `title`         | string      | 필수        | 포함 | 공지 제목 |
| `content`       | string      | 필수        | 포함 | 공지 본문 |

생성 요청 예시:

```json
{
    "type": "PERMANENT",
    "translations": [
        {
            "language_code": "KO",
            "title": "안전 수칙",
            "content": "안전요원의 안내를 따라 주세요."
        },
        {
            "language_code": "EN",
            "title": "Safety Guidelines",
            "content": "Please follow the safety staff's instructions."
        },
        {
            "language_code": "CHN",
            "title": "安全须知",
            "content": "请遵循安全人员的指引。"
        }
    ]
}
```

성공 응답 예시:

```json
{
    "id": 42,
    "type": "PERMANENT",
    "created_at": "2026-10-05T13:00:00+09:00",
    "translations": [
        {
            "id": 201,
            "notice_id": 42,
            "language_code": "CHN",
            "title": "安全须知",
            "content": "请遵循安全人员的指引。"
        },
        {
            "id": 202,
            "notice_id": 42,
            "language_code": "EN",
            "title": "Safety Guidelines",
            "content": "Please follow the safety staff's instructions."
        },
        {
            "id": 203,
            "notice_id": 42,
            "language_code": "KO",
            "title": "안전 수칙",
            "content": "안전요원의 안내를 따라 주세요."
        }
    ]
}
```

### 5.8 LostItem 스키마

기본 리소스:

| 필드           | 타입                  | POST          | PATCH               | 설명                         |
| -------------- | --------------------- | ------------- | ------------------- | ---------------------------- |
| `id`           | integer               | 서버 생성     | 수정 불가           | 분실물 ID                    |
| `image_url`    | string \| null        | 선택          | 선택                | 이미지 S3 key, 기본값 `null` |
| `is_returned`  | boolean               | 필수          | 선택                | 반환 여부                    |
| `created_at`   | datetime string       | 서버 생성     | 수정 불가           | 등록 시각                    |
| `translations` | LostItemTranslation[] | 필수, KO 포함 | 선택, 언어별 upsert | 전체 번역                    |

`LostItemTranslation`:

| 필드             | 타입        | 요청        | 응답 | 설명                           |
| ---------------- | ----------- | ----------- | ---- | ------------------------------ |
| `id`             | integer     | 보내지 않음 | 포함 | 번역 ID                        |
| `lost_item_id`   | integer     | 보내지 않음 | 포함 | 분실물 ID                      |
| `language_code`  | string enum | 필수        | 포함 | 번역 언어                      |
| `title`          | string      | 필수        | 포함 | 분실물 제목                    |
| `description`    | string      | 선택        | 포함 | 분실물 설명, 생략 시 빈 문자열 |
| `found_location` | string      | 선택        | 포함 | 습득 장소, 생략 시 빈 문자열   |

## 6. 삭제 규칙

모든 삭제는 soft delete가 아닌 영구 삭제다.

| 삭제 대상   | 동작                                                                                  |
| ----------- | ------------------------------------------------------------------------------------- |
| Category    | CategoryTranslation은 연쇄 삭제한다. Place가 하나라도 있으면 `409 DELETE_CONFLICT`다. |
| Place       | PlaceTranslation, 하위 Menu, 각 MenuTranslation을 모두 연쇄 삭제한다.                 |
| Menu        | MenuTranslation을 연쇄 삭제한다.                                                      |
| Performance | PerformanceTranslation을 연쇄 삭제한다.                                               |
| Notice      | NoticeTranslation을 연쇄 삭제한다.                                                    |
| LostItem    | LostItemTranslation을 연쇄 삭제한다.                                                  |

존재하지 않는 ID의 삭제는 `404 RESOURCE_NOT_FOUND`다. 성공한 삭제는 빈
본문의 `204 No Content`를 반환한다.

Category 삭제 충돌 예시:

```json
{
    "code": "DELETE_CONFLICT",
    "message": "장소가 연결된 카테고리는 삭제할 수 없습니다.",
    "details": [
        {
            "field": "category_id",
            "reason": "연결된 장소를 먼저 삭제해야 합니다."
        }
    ]
}
```

## 7. ISR 재검증

### 7.1 자동 재검증

Backoffice의 기본 리소스 `POST`, `PATCH`, `DELETE`와 번역 `DELETE`가
DB transaction을 성공적으로 commit한 뒤 해당 Customer 페이지의 ISR
재검증을 요청한다.

| 변경 리소스           | 재검증 target  |
| --------------------- | -------------- |
| Category, Place, Menu | `PLACES`       |
| Performance           | `PERFORMANCES` |
| Notice                | `NOTICES`      |
| LostItem              | `LOST_ITEMS`   |

자동 재검증은 post-commit best-effort 작업이다. CRUD 성공 응답은 DB 반영
성공을 의미하며 재검증 완료를 의미하지 않는다. 자동 요청 실패는
운영 로그와 모니터링에 기록하고 운영자가 수동 재검증 API로 재시도한다.

### 7.2 수동 재검증

#### POST `/api/v1/revalidations`

Bearer 인증이 필요하다.

요청:

```json
{
    "target": "NOTICES"
}
```

| 필드     | 타입        | 필수 | 허용값                                            |
| -------- | ----------- | ---- | ------------------------------------------------- |
| `target` | string enum | 예   | `PLACES`, `PERFORMANCES`, `NOTICES`, `LOST_ITEMS` |

요청을 접수하면 `202 Accepted`를 반환한다.

```json
{
    "target": "NOTICES",
    "accepted": true
}
```

`202`는 재검증 요청을 접수했다는 의미이며 프론트엔드 재생성 완료를
보장하지 않는다. 요청 자체를 접수하지 못하면
`500 INTERNAL_SERVER_ERROR`를 반환한다. ERD에 작업 상태 모델이 없으므로
재검증 상태 조회 API는 제공하지 않는다.

## 8. ERD와 API 매핑

| ERD                     | Customer 표현                                             | Backoffice 표현                 |
| ----------------------- | --------------------------------------------------------- | ------------------------------- |
| CATEGORY                | 선택 언어의 `name`을 평탄화                               | 기본 필드와 `translations`      |
| CATEGORY_TRANSLATION    | `language_code`, `name`                                   | 자식 ID와 FK를 포함한 번역 배열 |
| PLACE                   | 선택 언어 장소 필드                                       | 기본 필드와 `translations`      |
| PLACE_TRANSLATION       | `language_code`, `name`, `host_college`, `description`    | 자식 ID와 FK를 포함한 번역 배열 |
| MENU                    | 장소 상세의 `menus`                                       | 독립 CRUD 리소스                |
| MENU_TRANSLATION        | 메뉴 번역 필드 평탄화                                     | 자식 ID와 FK를 포함한 번역 배열 |
| PERFORMANCE             | 선택 언어 공연 필드                                       | 기본 필드와 `translations`      |
| PERFORMANCE_TRANSLATION | `language_code`, `title`, `description`                   | 자식 ID와 FK를 포함한 번역 배열 |
| NOTICE                  | 일반·상시 목록, 최근 일반 공지와 공통 상세                | 기본 필드와 `translations`      |
| NOTICE_TRANSLATION      | `language_code`, `title`, `content`                       | 자식 ID와 FK를 포함한 번역 배열 |
| LOST_ITEM               | 선택 언어 분실물 필드                                     | 기본 필드와 `translations`      |
| LOST_ITEM_TRANSLATION   | `language_code`, `title`, `description`, `found_location` | 자식 ID와 FK를 포함한 번역 배열 |

이미지 업로드 자체는 ERD 리소스를 추가하지 않는다. URL 발급 API는
presigned PUT URL과 S3 object key를 반환하고, ERD에 이미 존재하는
`category_icon_uri`, `place_image_uri`, `image_url`, `image_uri` 필드가
업로드 완료 후 해당 key를 저장한다. 이 네 필드는 모두 nullable이며
이미지를 올리지 않은 행은 `null`로 남는다.

ERD에는 구역 문자가 없으므로 API가 `A1`과 같은 구역 번호를 조합하지
않는다. `category_sequence`, `x`, `y`만 반환하고 화면 표기 규칙은
프론트엔드 계약으로 둔다.

## 9. 계약 검증 시나리오

1. 일반 공지 목록에는 `type=GENERAL`만, 상시 공지 목록에는
   `type=PERMANENT`만
   포함된다.
2. 최근 공지 API는 `type=GENERAL` 중 `created_at DESC, id DESC`의 첫 번째
   공지만 반환하며 상시 공지를 반환하지 않는다.
3. 일반 공지가 없을 때 최근 공지 API는 빈 본문의 `204 No Content`를
   반환한다.
4. `/notices/permanent`와 `/notices/latest`는 동적 notice ID 경로로
   처리되지 않는다.
5. 모든 Customer 단건 조회는 선택 query인 `language_code`만 지원하고
   생략 시 `KO`를 사용한다. 목록 전용 query를 전달하면
   `422 VALIDATION_ERROR`다.
6. 요청 언어 번역이 없는 항목은 목록에서 제외되고 단건 조회는
   `404 TRANSLATION_NOT_FOUND`다.
7. Backoffice 단건 조회는 query parameter를 받지 않고 존재하는 모든
   번역과 각 번역의 ID, FK를 반환한다.
8. 모든 기본 리소스 생성 요청은 `KO` 번역을 정확히 1개 포함하며,
   `EN`과 `CHN`은 생략할 수 있다.
9. `PATCH`에 전달한 언어는 update 또는 insert되고, 전달하지 않은
   언어의 번역과 번역 ID는 유지된다.
10. `EN`과 `CHN` 번역은 별도 `DELETE`로 삭제할 수 있지만 `KO` 번역
    삭제는 `409 DELETE_CONFLICT`다.
11. URL 발급 API는 허용된 JPEG, PNG, WebP와 10 MiB 이하의 선언 크기에
    대해서만 5분짜리 presigned PUT URL을 반환한다.
12. S3 PUT은 응답에 포함된 Content-Type과 `If-None-Match: *` header를
    사용하며 기존 key를 덮어쓰지 않는다.
13. 리소스 `POST` 또는 `PATCH`는 `HeadObject`와 image signature로
    실제 객체의 존재, prefix, 크기와 형식을 재검증한다.
14. 존재하지 않거나 prefix가 다른 key, 중복 key는
    `422 INVALID_IMAGE`이며 다른 리소스가 사용 중인 key는
    `409 IMAGE_ALREADY_ATTACHED`다.
15. 리소스에 연결되지 않거나 참조가 제거된 이미지는 24시간 유예 후
    cleanup 대상이 된다.
16. 잘못된 enum, 중복 언어, 빈 `translations`, 역전된 시작·종료 시각은
    `422 VALIDATION_ERROR`다. 시작과 종료가 같은 값이면 허용된다.
17. 이미지 필드를 생략하거나 `null`로 보낸 `POST`는 성공하고, 응답의
    해당 필드는 `null`이다.
18. `place_image_uri`에 빈 배열 `[]`, `null` 원소 또는 중첩 배열을
    보내면 `422 VALIDATION_ERROR`다.
19. 이미지 필드에 `null`을 보낸 `PATCH`는 연결을 해제하고, 해제된
    object key는 cleanup 대상이 된다.
20. 번역의 `description`과 `found_location`을 생략한 요청은 성공하고
    빈 문자열로 저장되며, 응답에는 `null`이 아닌 빈 문자열로 포함된다.
21. 응답의 `translations`는 `CHN`, `EN`, `KO` 순으로 정렬된다.
22. 토큰 발급 요청은 IP당 rolling 60초 동안 5회까지만 허용된다.
23. 만료, 잘못된 서명, 잘못된 `iss` 또는 `aud`의 JWT는
    `401 INVALID_TOKEN`이다.
24. Place 삭제 시 연결된 Menu와 모든 번역이 삭제된다.
25. Place가 연결된 Category 삭제는 `409 DELETE_CONFLICT`이며 어떤 행도
    삭제되지 않는다.
26. Backoffice 쓰기 transaction이 commit된 뒤 올바른 ISR target의
    재검증이 요청된다.
