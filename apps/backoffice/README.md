# Backoffice API

Quinquatria 운영자용 FastAPI 애플리케이션입니다.

저장소 루트에서 다음 명령으로 개발 서버를 실행합니다.

```bash
uv --directory apps/backoffice run fastapi dev
```

## 이미지 cleanup

연결되지 않았거나 해제된 S3 객체를 24시간 유예 뒤에 회수한다.

```bash
uv run --all-packages python -m backoffice.images
```

멱등하므로 반복 실행해도 안전하다. 실행 주기와 인프라 요구사항은
[배포 계약](../../docs/deploy/s3-image-storage.md)을 따른다.
