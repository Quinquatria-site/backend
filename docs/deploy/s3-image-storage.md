# 이미지 스토리지 배포 계약

| 항목      | 값                                                        |
| --------- | --------------------------------------------------------- |
| 대상 이슈 | [#9](https://github.com/Quinquatria-site/backend/issues/9) |
| 작성일    | 2026-09-16                                                 |
| 기준 문서 | [API 명세 §4.5, §4.6](../API_SPEC.md)                      |

애플리케이션은 아래 조건이 갖춰진 환경만 가정한다. 이 문서가 인프라와
애플리케이션 사이의 계약이다.

## 1. Bucket

- Block Public Access 네 항목을 모두 켠다.
- 버전 관리는 켜지 않는다. 이미지는 immutable하게 다루며 교체는 새 key로
  한다. 버전이 쌓이면 cleanup이 회수하지 못하는 사본이 남는다.
- object key prefix는 다음 다섯 개다. 다른 prefix에 쓰지 않는다.

  | 용도                | prefix                |
  | ------------------- | --------------------- |
  | `CATEGORY_ICON`     | `images/category/`    |
  | `PLACE_IMAGE`       | `images/place/`       |
  | `MENU_IMAGE`        | `images/menu/`        |
  | `PERFORMANCE_IMAGE` | `images/performance/` |
  | `LOST_ITEM_IMAGE`   | `images/lost-item/`   |

## 2. CloudFront

- 원본 읽기는 CloudFront OAC만 허용한다. bucket policy의 principal을 그
  distribution으로 한정한다.
- Customer 프론트엔드가 object key 앞에 붙일 asset origin이 이
  distribution이다. 백엔드는 key만 반환한다 (명세 §2.2).

## 3. CORS

Backoffice origin에서 S3로 직접 PUT하므로 bucket CORS에 다음만 연다.

| 항목           | 값                              |
| -------------- | ------------------------------- |
| AllowedOrigins | Backoffice 배포 origin만        |
| AllowedMethods | `PUT`                           |
| AllowedHeaders | `Content-Type`, `If-None-Match` |
| ExposeHeaders  | 없음                            |

`*`를 쓰지 않는다. `GET`을 열지 않는다. 읽기는 CloudFront가 맡는다.

## 4. IAM

애플리케이션에 정적 AWS access key를 주지 않는다. workload IAM role의 임시
credential만 쓴다. 설정에는 키를 받는 필드 자체가 없다.

role에 부여할 최소 권한은 다음이다.

- 위 다섯 prefix에 대한 `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`
- bucket에 대한 `s3:ListBucket` (cleanup의 고아 조회)

`s3:*`와 계정 전역 리소스를 쓰지 않는다.

## 5. 조건부 쓰기

발급하는 presigned URL은 `If-None-Match: *`를 서명 대상 헤더에 포함한다.
bucket policy에서도 이 조건이 없는 `PutObject`를 거부해, 서명을 우회한
덮어쓰기를 막는다.

## 6. cleanup 실행

`python -m backoffice.images`를 주기적으로 실행한다.

- 권장 주기: 1시간
- 실행 주체는 배포 환경의 스케줄러다 (EventBridge 규칙, ECS Scheduled
  Task 등). 애플리케이션 코드에 주기를 넣지 않는다.
- 멱등하므로 중복 실행과 중간 실패가 모두 안전하다.
- API 프로세스와 분리해 실행한다.

## 7. 환경변수

| 이름                                   | 필수   | 기본값     |
| -------------------------------------- | ------ | ---------- |
| `DATABASE_URL`                         | 예     | 없음       |
| `BACKOFFICE_S3_BUCKET`                 | 예     | 없음       |
| `BACKOFFICE_S3_REGION`                 | 예     | 없음       |
| `BACKOFFICE_S3_ENDPOINT_URL`           | 아니요 | 없음       |
| `BACKOFFICE_PRESIGNED_URL_TTL_SECONDS` | 아니요 | `300`      |
| `BACKOFFICE_MAX_IMAGE_BYTES`           | 아니요 | `10485760` |
| `BACKOFFICE_CLEANUP_GRACE_SECONDS`     | 아니요 | `86400`    |
| `BACKOFFICE_CLEANUP_BATCH_SIZE`        | 아니요 | `500`      |

`DATABASE_URL`만 앱 prefix가 없다. Backoffice와 Customer가 같은 DB를 쓰고
`alembic upgrade`도 같은 변수를 읽으므로, 앱마다 다른 이름을 두면 한쪽만
바꿨을 때 서로 다른 DB를 가리켜도 아무도 알아채지 못한다. cleanup 작업도
이 변수를 필요로 한다.

배포 환경은 위 변수를 플랫폼이 직접 주입한다. 저장소의 `.env.example`과
개발자가 만드는 `.env`는 로컬 전용이며 배포에 쓰지 않는다. 애플리케이션 코드는
환경변수만 읽고 `.env`를 열지 않으므로, 이 파일의 존재 여부가 배포 동작을
바꾸지 않는다.

## 8. 로그

- presigned URL의 query string은 만료 전까지 해당 key에 대한 업로드 권한
  그 자체다. access log와 application log에서 마스킹한다.
- 응답 본문 외 어디에도 서명을 남기지 않는다.
- bucket 이름과 내부 key 구조를 오류 응답에 담지 않는다.
