# GitHub Actions 자동 배포 (SSM)

`main`의 CI가 성공하면 [`deploy.yml`](../../.github/workflows/deploy.yml)이
EC2에 배포합니다. EC2의 22번 포트와 정적 AWS 키 없이 동작합니다.

```
main push ─▶ CI 성공 ─▶ Deploy (production 승인)
                          ├─ OIDC로 배포 role assume
                          ├─ CUSTOMER_ENV, BACKOFFICE_ENV → Parameter Store(SecureString)
                          └─ SSM Run Command ─▶ EC2: .github/deploy/ec2-deploy.sh
                                                 ├─ Parameter Store → *.env
                                                 ├─ git checkout <커밋>
                                                 ├─ docker compose build / alembic / up -d
                                                 └─ 127.0.0.1:8001, 8002 응답 확인
```

비밀값은 SSM 명령 본문에 넣지 않습니다. 명령 본문은 SSM 실행 기록에 평문으로
남기 때문에, 비밀값은 Parameter Store의 SecureString으로만 전달합니다.

## 전제

- EC2 서버 준비와 첫 수동 배포가 끝나 있어야 합니다. `/opt/quinquatria`에
  `backend` 저장소와 `compose.yaml`이 있어야 합니다.
- EC2에 aws CLI가 설치돼 있어야 합니다(`sudo snap install aws-cli --classic`).
- **`main` 브랜치 보호 규칙**(PR 필수, CI 통과 필수, force push 금지)을 먼저
  켭니다. 보호 규칙이 없으면 `main`에 들어간 모든 push가 운영에 배포됩니다.

## 1. EC2 인스턴스 role

기존 S3 정책에 다음 두 가지를 추가합니다.

- AWS 관리형 정책 `AmazonSSMManagedInstanceCore`
- 환경변수 파라미터 읽기

```json
{
  "Effect": "Allow",
  "Action": "ssm:GetParameter",
  "Resource": "arn:aws:ssm:ap-northeast-2:<account-id>:parameter/quinquatria/*"
}
```

기본 키(`aws/ssm`)로 암호화하면 KMS 권한은 따로 필요하지 않습니다. Ubuntu
AMI에는 SSM Agent가 기본 설치돼 있습니다. Systems Manager → Fleet Manager에서
인스턴스가 "온라인"으로 보이면 준비된 것입니다.

## 2. GitHub OIDC 공급자

IAM → 자격 증명 공급자 → 공급자 추가:

| 항목 | 값 |
| --- | --- |
| 유형 | OpenID Connect |
| 공급자 URL | `https://token.actions.githubusercontent.com` |
| 대상 | `sts.amazonaws.com` |

## 3. 배포 role

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
      "Sid": "ReadCommandResult",
      "Effect": "Allow",
      "Action": "ssm:GetCommandInvocation",
      "Resource": "*"
    }
  ]
}
```

`GetCommandInvocation`은 리소스 단위 제한을 지원하지 않아 `*`를 씁니다.

## 4. GitHub Environment

Settings → Environments → `production`을 만듭니다.

| 종류 | 이름 | 값 |
| --- | --- | --- |
| Required reviewers | - | 배포를 승인할 사람 |
| Deployment branches | - | `main`만 허용 |
| Secret | `CUSTOMER_ENV` | `customer.env` 파일 내용 전체 |
| Secret | `BACKOFFICE_ENV` | `backoffice.env` 파일 내용 전체 |
| Variable | `AWS_DEPLOY_ROLE_ARN` | 3의 배포 role ARN |
| Variable | `EC2_INSTANCE_ID` | `i-...` |

`*_ENV` secret에는 `KEY=value` 형식의 줄을 그대로 붙여 넣습니다. 형식은
[EC2 운영 배포](../DEPLOY_EC2.md)의 환경변수 절을 따릅니다. 값을 바꾸면 다음
배포부터 반영됩니다. 바로 반영하려면 Actions → Deploy → Run workflow를
실행합니다.

## 동작

- `workflow_run`은 기본 브랜치(`main`)에 있는 workflow 파일만 실행합니다. 이
  파일이 `main`에 들어간 다음 push부터 자동 배포가 시작됩니다.
- 배포는 한 번에 하나씩만 실행합니다. 배포가 진행 중일 때 들어온 다음 배포는
  앞의 배포가 끝날 때까지 기다립니다.
- 서버 스크립트는 `main` 브랜치를 배포 커밋으로 맞춘 뒤(`checkout -B main`)
  빌드합니다. 서버의 저장소에서 파일을 직접 고쳐 두면 checkout이 실패하고
  배포가 중단됩니다.
- 실행 결과는 Actions 로그의 stdout, stderr 그룹과 Systems Manager →
  Run Command 기록에서 볼 수 있습니다. 출력은 최대 24,000자까지만 남습니다.

## 롤백

Actions → Deploy → Run workflow에서 브랜치 대신 이전 커밋을 배포할 수는
없습니다. 되돌릴 때는 `main`에 revert PR을 병합합니다. 마이그레이션은 자동으로
되돌리지 않습니다.
