# Cloudtype 임시 배포

프론트가 develop 브랜치의 구현을 바로 연결해 볼 수 있도록 Cloudtype에 띄우는
**임시** 배포 절차입니다. 정식 운영 배포가 아니며, 아래 "임시 배포 한정 예외"는
정식 배포에 가져가지 않습니다.

## 구성

하나의 Cloudtype 프로젝트에 서비스 3개를 둡니다.

| 서비스 | 템플릿 | 소스 |
| --- | --- | --- |
| `postgresql` | PostgreSQL | - |
| `customer` | Dockerfile | GitHub 저장소 `develop` 브랜치, `Dockerfile.customer` |
| `backoffice` | Dockerfile | GitHub 저장소 `develop` 브랜치, `Dockerfile.backoffice` |

- 두 앱 모두 빌드 컨텍스트는 저장소 루트이고 컨테이너 포트는 `8000`입니다.
- develop에 push되면 두 앱이 자동으로 다시 배포되도록 브랜치 자동 배포를 켭니다.
- `backoffice`는 기동할 때 `alembic upgrade head`를 먼저 실행합니다. 이미 최신이면
  아무것도 하지 않습니다. 두 인스턴스가 동시에 마이그레이션하지 않도록
  **`backoffice` 인스턴스는 1개로 둡니다.**
- `customer`는 스키마를 만들지 않습니다. 처음 배포할 때는 `backoffice`가 먼저
  떠서 마이그레이션을 마친 뒤 `customer`를 띄웁니다.

## 환경변수

`DATABASE_URL`은 두 앱에 같은 값을 넣습니다. Cloudtype PostgreSQL 서비스의
내부 접속 정보로 `postgresql+psycopg://<user>:<password>@<host>:<port>/<db>`
형식을 만듭니다.

### 공통

| 이름 | 값 |
| --- | --- |
| `DATABASE_URL` | 위 형식의 내부 접속 URL |
| `CORS_ALLOW_ORIGINS` | 프론트 origin을 쉼표로 구분 (예: `http://localhost:3000,https://<front-domain>`) |

`CORS_ALLOW_ORIGINS`에는 scheme과 port까지 정확히 적고, 끝에 `/`를 붙이지
않습니다. 비워 두면 브라우저 호출이 CORS로 막힙니다.

### backoffice 전용

| 이름 | 값 |
| --- | --- |
| `BACKOFFICE_ISSUANCE_CODE` | 16자 이상, 공백 없음. 로컬 값과 다르게 둔다 |
| `BACKOFFICE_JWT_SIGNING_KEY` | 32 byte 이상 무작위 값 (`openssl rand -base64 48`) |
| `BACKOFFICE_S3_BUCKET` | 업로드 버킷 이름 |
| `BACKOFFICE_S3_REGION` | 버킷 리전 (예: `ap-northeast-2`) |
| `AWS_ACCESS_KEY_ID` | 아래 임시 IAM 사용자의 키 |
| `AWS_SECRET_ACCESS_KEY` | 위 키의 secret |

`BACKOFFICE_S3_ENDPOINT_URL`은 넣지 않습니다. 비밀값은 Cloudtype의 secret
환경변수로 넣고, 발급 코드는 프론트 테스트 담당자에게만 따로 전달합니다.

## 임시 배포 한정 예외: 정적 AWS 키

설계상 Backoffice는 workload IAM role의 임시 credential만 씁니다
([.env.example](../.env.example)). Cloudtype에는 IAM role을 붙일 수 없어서, 이
배포에서만 정적 키를 botocore 표준 환경변수로 넣습니다. 앱 코드는 바뀌지
않습니다.

- 이 용도 전용 IAM 사용자를 새로 만들고 다른 곳에 재사용하지 않습니다.
- 권한은 업로드 버킷 하나로 제한합니다.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::<bucket>/*"
    },
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<bucket>"
    }
  ]
}
```

- 임시 배포를 내리면 키를 비활성화하고 IAM 사용자를 삭제합니다.

## S3 버킷 CORS

프론트는 presigned URL로 브라우저에서 S3에 직접 `PUT`합니다. 버킷 CORS에
프론트 origin을 허용해야 합니다. presigned URL에는 `Content-Type`과
`If-None-Match`가 서명되어 있어서 두 헤더를 모두 허용해야 합니다.

```json
[
  {
    "AllowedOrigins": ["http://localhost:3000", "https://<front-domain>"],
    "AllowedMethods": ["PUT"],
    "AllowedHeaders": ["content-type", "if-none-match"],
    "MaxAgeSeconds": 3000
  }
]
```

## 이 배포에서 돌지 않는 것

- 이미지 cleanup 작업(`python -m backoffice.images`)은 스케줄하지 않습니다.
  임시 배포 동안 버려진 업로드 객체는 버킷에 남습니다.
- 요청 수 제한 같은 reverse proxy 보호가 없습니다. 발급 코드를 공개된 곳에
  적지 않습니다.

## 확인

배포 후 다음 요청으로 확인합니다.

```bash
curl https://<customer-domain>/api/v1/notices
curl -X POST https://<backoffice-domain>/api/v1/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"issuance_code": "<발급 코드>"}'
```

API 문서는 각 앱의 `/docs`에서 볼 수 있습니다.

로컬에서 같은 이미지를 확인하려면 저장소 루트에서 빌드합니다.

```bash
docker build -f Dockerfile.customer -t quinquatria-customer .
docker build -f Dockerfile.backoffice -t quinquatria-backoffice .
```
