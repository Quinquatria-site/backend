#!/usr/bin/env bash
# deploy.yml이 SSM Run Command로 EC2에서 root로 실행한다.
# 출력이 SSM 실행 기록과 Actions 로그에 남으므로 set -x와 비밀값 출력을 쓰지 않는다.
set -euo pipefail

: "${IMAGE_REGISTRY:?IMAGE_REGISTRY가 필요합니다}"
: "${IMAGE_TAG:?IMAGE_TAG가 필요합니다}"
REGION="${AWS_REGION:-ap-northeast-2}"
APP_DIR=/opt/quinquatria
# SSM 셸의 PATH에는 snap으로 설치한 aws CLI가 없을 수 있다.
export PATH="$PATH:/snap/bin:/usr/local/bin"

cd "$APP_DIR"

tmp=""
cleanup() { if [ -n "$tmp" ]; then rm -f "$tmp"; fi; }
trap cleanup EXIT
for app in customer backoffice; do
    tmp="$(mktemp "$APP_DIR/.$app.env.XXXXXX")"
    aws ssm get-parameter --region "$REGION" --name "/quinquatria/$app.env" \
        --with-decryption --query Parameter.Value --output text > "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$app.env"
    tmp=""
done
echo "환경변수 파일 갱신 완료"

# compose.yaml이 변수 치환에 쓰는 값. 직전 태그를 남겨 수동 롤백에 쓴다.
if [ -f .env ]; then
    grep '^IMAGE_TAG=' .env | sed 's/^/PREVIOUS_/' > .env.previous || true
fi
printf 'IMAGE_REGISTRY=%s\nIMAGE_TAG=%s\n' "$IMAGE_REGISTRY" "$IMAGE_TAG" > .env

aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "$IMAGE_REGISTRY" > /dev/null
docker compose pull --quiet
docker compose run --rm backoffice alembic upgrade head
docker compose up -d --remove-orphans

for port in 8001 8002; do
    for attempt in $(seq 1 30); do
        if curl -fsS -o /dev/null "http://127.0.0.1:$port/api/v1/"; then
            echo "127.0.0.1:$port 응답 확인"
            break
        fi
        if [ "$attempt" -eq 30 ]; then
            echo "127.0.0.1:$port 가 60초 안에 응답하지 않았습니다" >&2
            docker compose ps >&2
            exit 1
        fi
        sleep 2
    done
done

# 실행 중이 아니고 만든 지 사흘이 지난 이미지만 지운다. 최근 이미지는 롤백용으로 남긴다.
docker image prune -af --filter 'until=72h' > /dev/null
echo "배포 완료: $IMAGE_TAG"
