# Backoffice API

Quinquatria 운영자용 FastAPI 애플리케이션입니다.

저장소 루트에서 다음 명령으로 개발 서버를 실행합니다.

```bash
uv --directory apps/backoffice run fastapi dev
```

## ISR 자동 재검증

장소·메뉴·공지·공연·분실물의 생성, 수정, 삭제, 카테고리 수정, 번역 삭제, 그리고
공연의 순서 변경과 live 지정이 DB에 commit되면 백그라운드에서 프런트엔드
`POST {USER_SITE_URL}/api/revalidate`를 호출합니다.
`Authorization: Bearer <REVALIDATE_SECRET>` 헤더와 `{"tag":"categories"}` 같은
본문을 사용합니다. 카테고리는 `categories`, 장소와 메뉴는 `places`, 공지는
`notices`, 공연은 `performances`, 분실물은 `lost-items` 태그입니다.

`USER_SITE_URL`은 프런트엔드 사이트의 기본 URL이고 `REVALIDATE_SECRET`은
수신기와 공유하는 비밀값입니다. 실행 환경에서 두 값을 주입합니다. 둘 중
하나가 비어 있으면 전송을 건너뜁니다. 비어 있지 않은 잘못된 설정이나
수신기 오류가 있어도 앱은 시작하고 이미 commit된 CRUD 응답은 성공으로
유지됩니다. 전송은 요청당 최대 10초, 1회 시도하며 리다이렉트를 따르지
않습니다. 실패 로그는 태그·실패 종류·HTTP 상태만 기록합니다.

재검증 요청은 별도 영속 큐 없이 처리하므로, CRUD 성공이 프런트엔드의
재생성 완료를 뜻하지는 않습니다. 수동 재검증 API는 아직 구현되지
않았습니다. 태그 전체 매핑과 수신기 응답 계약은
[API 명세](../../docs/API_SPEC.md#7-isr-재검증)를 참고합니다.

## 지도 장소 시드

지도에 표시할 장소의 카테고리·구역 번호·좌표를 운영 DB에 한 번 넣는다.
운영 시간과 번역은 이후 Backoffice `PATCH`로 채운다. 카테고리는 migration
0006이 넣으므로 `alembic upgrade head` 뒤에 실행한다.

```bash
uv run --all-packages python -m backoffice.domains.catalog.place_seed [JSON 경로]
```

경로를 생략하면 `src/backoffice/domains/catalog/data/map_places.json`을 쓴다.
항목은 `code`(CATEGORY enum), `category_sequence`, `x`, `y`만 받는다. 파일
전체가 한 transaction이며, 같은 구역 번호가 같은 좌표에 이미 있으면 건너뛰므로
다시 실행해도 안전하다. 다른 좌표에 있으면 아무것도 넣지 않고 실패한다.
넣은 장소는 Customer 지도에 빈 마커로 바로 보이므로, 새로 넣은 것이 있으면
commit 뒤 `places` ISR 재검증을 보낸다(`USER_SITE_URL`, `REVALIDATE_SECRET` 필요).

## 이미지 cleanup

연결되지 않았거나 해제된 S3 객체를 24시간 유예 뒤에 회수한다.

```bash
uv run --all-packages python -m backoffice.images
```

멱등하므로 반복 실행해도 안전하다. 실행 주기와 인프라 요구사항은
[배포 계약](../../docs/deploy/s3-image-storage.md)을 따른다.
