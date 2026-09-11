# Common

Customer API와 Backoffice API가 공유하는 v1 계약 코드입니다.
[API 명세](../../docs/API_SPEC.md) §2 공통 규칙을 구현합니다.

배포되는 애플리케이션이 아니라 두 앱이 의존하는 라이브러리입니다.

| 모듈 | 책임 |
| --- | --- |
| `enums.py` | `language_code`와 리소스 enum |
| `types.py` | ID, price, datetime 공통 필드 타입 |
| `errors.py` | 오류 코드와 `ApiError` 예외 계층 |
| `handlers.py` | 명세 오류 본문으로 변환하는 전역 예외 핸들러 |
| `query.py` | `extra="forbid"` query parameter 모델 |
| `pagination.py` | 목록 응답 `Page` 구조 |
| `app.py` | 두 앱이 호출하는 애플리케이션 팩토리 |
