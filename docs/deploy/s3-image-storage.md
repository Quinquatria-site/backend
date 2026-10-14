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
- object key prefix는 다음 여섯 개다. 다른 prefix에 쓰지 않는다.

  | 용도                | prefix                |
  | ------------------- | --------------------- |
  | `CATEGORY_ICON`     | `images/category/`    |
  | `PLACE_IMAGE`       | `images/place/`       |
  | `MENU_IMAGE`        | `images/menu/`        |
  | `PERFORMANCE_IMAGE` | `images/performance/` |
  | `NOTICE_IMAGE`      | `images/notice/`      |
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

- 위 여섯 prefix에 대한 `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`
- bucket에 대한 `s3:ListBucket` (cleanup의 고아 조회)

`s3:*`와 계정 전역 리소스를 쓰지 않는다.

## 5. 조건부 쓰기

발급하는 presigned URL은 `If-None-Match: *`를 서명 대상 헤더에 포함한다.
bucket policy에서도 이 조건이 없는 `PutObject`를 거부해, 서명을 우회한
덮어쓰기를 막는다.

## 6. cleanup 실행

`python -m backoffice.images`를 주기적으로 실행한다.

- 권장 주기: 1시간
- 실행 주체는 배포 환경의 스케줄러다. 애플리케이션 코드에 주기를 넣지 않는다.
- 멱등하므로 중복 실행과 중간 실패가 모두 안전하다.
- API 프로세스와 분리해 실행한다.

### GitHub Actions 스케줄 (Cloudtype 임시 배포 한정)

> **Cloudtype 임시 배포에서만 쓰는 구성이다.** runner가 VPC 밖에서 돌기
> 때문에 DB를 인터넷에 열어야 성립한다. 정식 배포에서 DB를 프라이빗
> 서브넷에 두면 runner가 닿지 못하므로, 그때는 이 workflow를 지우고
> EventBridge Scheduler + ECS Fargate 작업으로 같은 이미지를
> `python -m backoffice.images` 명령으로 VPC 안에서 실행한다. 자격 증명은
> task role이 맡고 DB는 외부에 열지 않는다.

현재 실행 주체는 [`image-cleanup.yml`](../../.github/workflows/image-cleanup.yml)이다.
매시 17분에 돌고, Actions 탭에서 수동으로도 실행할 수 있다. GitHub의
`schedule`은 기본 브랜치의 workflow만 실행하며 부하에 따라 지연될 수 있다.

전제 조건:

- **DB 접근:** runner가 운영 DB에 닿아야 한다. Cloudtype 내부 호스트는
  외부에서 닿지 않으므로 PostgreSQL 서비스의 외부 접속을 켜고, 외부 주소로
  만든 URL을 쓴다. 외부에 여는 만큼 강한 비밀번호를 둔다.
- **AWS 권한:** 정적 키 없이 GitHub OIDC로 cleanup 전용 role을 assume한다.
  trust policy의 `sub`는 `repo:Quinquatria-site/backend:environment:production`으로
  한정한다. 권한은 회수에 필요한 두 가지뿐이다.

  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": "s3:ListBucket",
        "Resource": "arn:aws:s3:::<bucket>",
        "Condition": { "StringLike": { "s3:prefix": "images/*" } }
      },
      {
        "Effect": "Allow",
        "Action": "s3:DeleteObject",
        "Resource": "arn:aws:s3:::<bucket>/images/*"
      }
    ]
  }
  ```

- **저장소 설정:** `production` environment에 아래 값을 둔다.

  | 종류     | 이름                    | 값                       |
  | -------- | ----------------------- | ------------------------ |
  | Secret   | `CLEANUP_DATABASE_URL`  | 외부 접속용 운영 DB URL  |
  | Variable | `AWS_CLEANUP_ROLE_ARN`  | 위 role의 ARN            |
  | Variable | `BACKOFFICE_S3_BUCKET`  | 업로드 버킷 이름         |
  | Variable | `BACKOFFICE_S3_REGION`  | 버킷 리전                |

`BACKOFFICE_ISSUANCE_CODE`와 `BACKOFFICE_JWT_SIGNING_KEY`는 설정 로딩에만
필요하고 cleanup은 쓰지 않는다. workflow가 실행마다 무작위 값을 만들어 넣으므로
운영 값을 등록하지 않는다.

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

`BACKOFFICE_MAX_IMAGE_BYTES`는 기본값보다 낮추는 것만 된다. 원장의
`ck_image_declared_size_in_range`와 `ck_image_byte_size_in_range`가 10 MiB로
고정돼 있어, 더 큰 값을 주면 앱이 뜨지 않는다. 상한을 실제로 올리려면 두
CHECK를 바꾸는 마이그레이션이 함께 필요하다.

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
- AWS SDK는 DEBUG에서 서명 값을 그대로 남기므로, 앱이 기동할 때
  `botocore.auth` 로거를 INFO로 내린다. 전역 로그 레벨을 DEBUG로 올려도
  서명은 올라오지 않는다. SDK 서명 과정을 디버깅하려면 코드에서 이 억제를
  빼야 한다.
- bucket 이름과 내부 key 구조를 오류 응답에 담지 않는다.
