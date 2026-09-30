# GitHub Actions 자동 배포 (ECR + SSM)

`main`의 CI가 성공하면 [`deploy.yml`](../../.github/workflows/deploy.yml)이
이미지를 ECR에 올리고 EC2에서 교체합니다. 운영 서버는 빌드하지 않고, 22번
포트와 정적 AWS 키 없이 동작합니다.

```
main push ─▶ CI 성공 ─▶ Deploy (production 승인)
                          ├─ OIDC로 배포 role assume
                          ├─ docker build → ECR push (태그 = 커밋 SHA, 있으면 생략)
                          ├─ CUSTOMER_ENV, BACKOFFICE_ENV → Parameter Store(SecureString)
                          └─ SSM Run Command ─▶ EC2 /opt/quinquatria
                                                 ├─ compose.yaml 갱신
                                                 ├─ Parameter Store → *.env
                                                 ├─ docker compose pull
                                                 ├─ alembic upgrade head
                                                 ├─ docker compose up -d
                                                 └─ 127.0.0.1:8001, 8002 응답 확인
```

비밀값은 SSM 명령 본문에 넣지 않습니다. 명령 본문은 SSM 실행 기록에 평문으로
남기 때문에, 비밀값은 Parameter Store의 SecureString으로만 전달합니다.

서버에 저장소를 clone하지 않습니다. [`compose.yaml`](../../.github/deploy/compose.yaml)은
배포할 때마다 저장소의 파일로 덮어씁니다. 서버에서 직접 고친 내용은 다음 배포에서
사라집니다.

## 1. ECR 저장소

ECR → 리포지토리 생성으로 두 개를 만듭니다.

| 이름 | 태그 변경 불가 |
| --- | --- |
| `quinquatria-customer` | 활성화(Immutable) |
| `quinquatria-backoffice` | 활성화(Immutable) |

태그는 커밋 SHA이므로 같은 태그를 덮어쓸 일이 없습니다. 불변으로 두면 롤백할
때 받은 이미지가 그 커밋의 이미지임을 보장합니다.

각 저장소에 수명 주기 정책을 두어 오래된 이미지를 지웁니다.

```json
{
  "rules": [
    {
      "rulePriority": 1,
      "description": "최근 30개만 보관",
      "selection": {
        "tagStatus": "any",
        "countType": "imageCountMoreThan",
        "countNumber": 30
      },
      "action": { "type": "expire" }
    }
  ]
}
```

## 2. EC2 인스턴스 role

기존 S3 정책에 다음을 추가합니다.

- AWS 관리형 정책 `AmazonSSMManagedInstanceCore`
- 환경변수 파라미터 읽기와 ECR pull

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadEnvParameters",
      "Effect": "Allow",
      "Action": "ssm:GetParameter",
      "Resource": "arn:aws:ssm:ap-northeast-2:<account-id>:parameter/quinquatria/*"
    },
    {
      "Sid": "EcrLogin",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "PullImages",
      "Effect": "Allow",
      "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
      "Resource": "arn:aws:ecr:ap-northeast-2:<account-id>:repository/quinquatria-*"
    }
  ]
}
```

기본 키(`aws/ssm`)로 암호화하면 KMS 권한은 따로 필요하지 않습니다.
`GetAuthorizationToken`은 리소스 단위 제한을 지원하지 않아 `*`를 씁니다.

## 3. 빈 서버 준비 (Ubuntu, 한 번만)

```bash
# Docker와 Compose 플러그인
curl -fsSL https://get.docker.com | sudo sh

# aws CLI
sudo snap install aws-cli --classic

# SSM Agent는 Ubuntu AMI에 기본 설치돼 있다. 동작 확인:
sudo snap services amazon-ssm-agent
```

컨테이너가 인스턴스 role을 쓸 수 있게 IMDS hop limit을 2로 올립니다.

```bash
aws ec2 modify-instance-metadata-options --instance-id <instance-id> \
  --http-tokens required --http-put-response-hop-limit 2
```

Systems Manager → Fleet Manager에서 인스턴스가 "온라인"이면 준비된 것입니다.
nginx와 TLS 설정은 [EC2 운영 배포](../DEPLOY_EC2.md)를 따릅니다. `/opt/quinquatria`와
그 안의 파일은 첫 배포가 만듭니다.

## 4. GitHub OIDC 공급자

IAM → 자격 증명 공급자 → 공급자 추가:

| 항목 | 값 |
| --- | --- |
| 유형 | OpenID Connect |
| 공급자 URL | `https://token.actions.githubusercontent.com` |
| 대상 | `sts.amazonaws.com` |

## 5. 배포 role

IAM → 역할 생성 → 웹 자격 증명 → 위 공급자를 선택합니다. 신뢰 정책은 이
저장소의 `production` Environment에서 실행된 job만 허용합니다.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<account-id>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:Quinquatria-site/backend:environment:production"
        }
      }
    }
  ]
}
```

권한 정책:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrLogin",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "PushImages",
      "Effect": "Allow",
      "Action": [
        "ecr:DescribeImages",
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": "arn:aws:ecr:ap-northeast-2:<account-id>:repository/quinquatria-*"
    },
    {
      "Sid": "WriteEnvParameters",
      "Effect": "Allow",
      "Action": "ssm:PutParameter",
      "Resource": "arn:aws:ssm:ap-northeast-2:<account-id>:parameter/quinquatria/*"
    },
    {
      "Sid": "RunDeployCommand",
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ec2:ap-northeast-2:<account-id>:instance/<instance-id>",
        "arn:aws:ssm:ap-northeast-2::document/AWS-RunShellScript"
      ]
    },
    {
      "Sid": "ManageDeployCommand",
      "Effect": "Allow",
      "Action": ["ssm:GetCommandInvocation", "ssm:CancelCommand"],
      "Resource": "*"
    }
  ]
}
```

`GetCommandInvocation`과 `CancelCommand`는 명령 단위로 리소스를 제한할 수 없어
`*`를 씁니다. `CancelCommand`는 상태 조회 한도를 넘었을 때 원격 명령을 취소하는 데
필요합니다.

## 6. GitHub 설정

먼저 **`main` 브랜치 보호 규칙**(PR 필수, CI 통과 필수, force push 금지)을
켭니다. 보호 규칙이 없으면 `main`에 들어간 모든 push가 운영에 배포됩니다.

Settings → Environments → `production`을 만듭니다.

| 종류 | 이름 | 값 |
| --- | --- | --- |
| Required reviewers | - | 배포를 승인할 사람 |
| Deployment branches | - | `main`만 허용 |
| Secret | `CUSTOMER_ENV` | `customer.env` 파일 내용 전체 |
| Secret | `BACKOFFICE_ENV` | `backoffice.env` 파일 내용 전체 |
| Variable | `AWS_DEPLOY_ROLE_ARN` | 5의 배포 role ARN |
| Variable | `EC2_INSTANCE_ID` | `i-...` |

`*_ENV` secret에는 `KEY=value` 형식의 줄을 그대로 붙여 넣습니다. 형식은
[EC2 운영 배포](../DEPLOY_EC2.md)의 환경변수 절을 따르며, IAM role을 쓰므로
`AWS_ACCESS_KEY_ID`와 `AWS_SECRET_ACCESS_KEY`는 넣지 않습니다.

## 동작

- `workflow_run`은 기본 브랜치(`main`)에 있는 workflow 파일만 실행합니다. 이
  파일이 `main`에 들어간 다음 push부터 자동 배포가 시작됩니다. 첫 배포는
  Actions → Deploy → Run workflow로 실행합니다.
- 자동 배포는 **`main` 최신 커밋만** 대상으로 합니다. 과거 커밋의 CI를 재실행하면
  그 성공 이벤트는 원래 SHA를 싣고 오므로, 최신이 아니면 승인 요청 없이 건너뜁니다.
  승인을 기다리는 사이 `main`이 바뀌면 그 실행은 실패하고 최신 커밋의 실행이
  이어서 배포합니다.
- 배포는 한 번에 하나씩만 실행하고, 진행 중인 배포는 취소하지 않습니다.
- EC2에서는 배포 전 구간을 `/var/lock/quinquatria-deploy.lock`으로 잠급니다.
  workflow가 조회를 끝낸 뒤 늦게 실행된 명령도 다른 배포와 겹치지 않습니다.
- 명령마다 보낸 시각을 싣고, 서버는 마지막으로 적용한 시각
  (`/opt/quinquatria/.deployed-sent-at`)보다 오래된 명령을 거부합니다. 늦게
  전달된 옛 명령이 더 최근 배포를 되돌리지 않습니다.
- SSM 전달 대기는 600초, 실행은 1800초로 제한합니다. 조회 한도를 넘기면
  workflow가 명령을 취소하고 종료를 확인합니다.
- secret 값을 바꾸면 다음 배포부터 반영됩니다. 바로 반영하려면 Run workflow를
  실행합니다. 같은 커밋이면 이미지를 다시 빌드하지 않습니다.
- 실행 결과는 Actions 로그의 stdout, stderr 그룹과 Systems Manager →
  Run Command 기록에서 볼 수 있습니다. 출력은 최대 24,000자까지만 남습니다.

## 롤백

Actions → Deploy → Run workflow에서 `image_tag`에 되돌릴 커밋의 SHA 40자를
넣습니다. `main` 이력에 있는 커밋만 받으며, 그 커밋의 이미지가 ECR에 있으면
빌드 없이 교체합니다. 앱 소스만 그 커밋에서 빌드하고 `compose.yaml`과 배포
스크립트는 실행 중인 workflow의 것을 쓰므로, 배포 파일이 생기기 전의 커밋으로도
되돌릴 수 있습니다.

서버에서 직접 되돌려야 할 때는 `/opt/quinquatria/.env.previous`에 직전 태그가
있습니다.

```bash
cd /opt/quinquatria
sudo sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=<이전 SHA>/" .env
sudo docker compose up -d
```

마이그레이션은 자동으로 되돌리지 않습니다. 스키마가 바뀐 배포를 되돌릴 때는
`alembic downgrade <revision>`이 안전한지 먼저 확인합니다.
