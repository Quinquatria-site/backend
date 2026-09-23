# Backoffice API

Quinquatria 운영자용 FastAPI 애플리케이션입니다.

저장소 루트에서 다음 명령으로 개발 서버를 실행합니다.

```bash
uv --directory apps/backoffice run fastapi dev
```

## ISR 재검증

인증된 `POST /api/v1/revalidations` 수동 API와 HTTP 전송기, DB commit 이후
자동 전송을 등록하는 hook을 제공한다. 요청에는 `target`, `resource_type`이
필수이고 `id`는 기본 리소스의 백엔드 양의 정수 ID다. 생략하거나 `null`이면
도메인 전체 재검증으로 취급한다. 허용 조합과 HTTP 계약은
[API 명세 §7](../../docs/API_SPEC.md#7-isr-재검증)을 따른다.

### 설정과 전송

실제 프론트엔드 수신기 주소를 `BACKOFFICE_REVALIDATION_URL` 환경변수로
주입한다. 다음 주소는 형식 예시이며 연결된 프론트엔드 주소가 아니다.

```text
BACKOFFICE_REVALIDATION_URL=https://example.invalid/api/revalidate
```

이 값이 없어도 앱은 기동한다. 실제 전송은 실패하므로 자동 요청은 실패
로그를 남기고, 수동 API는 `500 INTERNAL_SERVER_ERROR`를 반환한다.
프론트엔드 수신기와 실제 환경의 URL 연결은 별도로 완료해야 한다.

전송기는 앱 lifespan 동안 `httpx.AsyncClient`를 공유하고 종료 시 닫는다.
시도당 전체 5초 제한이며 통신 오류·timeout 또는 `502`, `503`, `504`에만
500ms 뒤 한 번 재시도한다. 전송 시간 예산은 최대 10.5초다. 나머지 실패는
재시도하지 않는다. 수동 API는 수신기 `2xx`를 확인한 뒤 `202`를 반환하며,
학생 페이지의 재생성 완료를 보장하지 않는다.

전송 본문은 `target`, `resource_type`, 선택적 `id`다. `id`가 없거나
`null`이면 전송 본문에서도 빠진다. `target`은 갱신할 도메인 범위이고 실제
페이지 경로와 cache tag는 프론트엔드가 결정한다. 전송 실패 후 재시도에서
중복 접수가 발생할 수 있으므로 수신기는 같은 요청을 반복 처리할 수 있어야
한다. 내구성 큐와 상태 조회 API는 제공하지 않는다.

### CRUD에 hook 연결

현재 구현 범위는 수동 API와 공통 전송·hook 기반이다. 실제 관리 CRUD
라우트는 아직 없으므로 자동 재검증이 모든 쓰기 경로에 연결된 상태가 아니다.
[카테고리·장소·메뉴 #3](https://github.com/Quinquatria-site/backend/issues/3),
[공연 #4](https://github.com/Quinquatria-site/backend/issues/4),
[공지 #5](https://github.com/Quinquatria-site/backend/issues/5),
[분실물 #7](https://github.com/Quinquatria-site/backend/issues/7) 구현에서 다음
hook을 연결해야 한다.

`backoffice.auth.dependencies.SessionDep`으로 주입받은 동일 세션에서 DB
변경 후 `mark_changed()`를 호출한다. 새 리소스는 `flush()`로 ID를 받은
뒤 등록하고, 삭제는 삭제할 기본 리소스 ID를 보존해 등록한다. 번역 삭제도
번역 ID가 아닌 기본 리소스 ID를 사용한다.

```python
from backoffice.revalidation.events import mark_changed
from backoffice.revalidation.schemas import ResourceType

# 공지 생성·수정·삭제 또는 공지 번역 삭제의 경우
mark_changed(session, ResourceType.NOTICE, notice_id)
```

live 변경과 reorder는 변경된 각 공연을 등록하지 않고, 한 번만 공연 도메인
전체를 등록한다.

```python
from backoffice.revalidation.events import mark_performances_changed

mark_performances_changed(session)
```

hook은 세션에 이벤트를 모으며 직접 HTTP 요청을 보내지 않는다. 요청 세션의
transaction이 성공적으로 commit되면 `BackgroundTasks`에 전송을 등록한다.
rollback이나 commit 실패에는 전송하지 않는다. 자동 전송의 최종 실패는
이미 성공한 CRUD 응답과 DB 변경을 유지하고 로그로 남긴다. 프로세스 종료로
유실된 요청과 실패한 요청은 운영자가 수동 API로 재시도한다.

### 검사

저장소 루트에서 기존 검사 명령을 사용한다. DB 통합 테스트의 Docker
요구사항은 [루트 README](../../README.md#검사)를 참고한다. 테스트에는
`--env-file`을 지정하지 않는다.

```bash
uv run --all-packages pytest apps/backoffice/tests
uv run ruff check .
uv run ruff format --check .
```

mock HTTP 전송과 임시 DB로 검증한 결과는 실제 프론트엔드 페이지가
재생성되었다는 증거와 구분한다. 배포 전 실제 수신기 연결과 학생 화면 반영을
별도로 확인한다.

## 이미지 cleanup

연결되지 않았거나 해제된 S3 객체를 24시간 유예 뒤에 회수한다.

```bash
uv run --all-packages python -m backoffice.images
```

멱등하므로 반복 실행해도 안전하다. 실행 주기와 인프라 요구사항은
[배포 계약](../../docs/deploy/s3-image-storage.md)을 따른다.
