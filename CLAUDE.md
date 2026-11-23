# PowerSeed — 작업 가이드

인플루언서 시딩 CRM (Django 6.1, Python 3.12+). 설계/로드맵: `docs/ROADMAP.md`. 진행 상황: `README.md`의 로드맵 체크리스트. **이어서 할 일·시작 명령: `docs/NEXT.md`** (작업을 마치면 갱신).

## 명령
- 테스트: `python manage.py test` (외부 API는 mock, 테스트는 각 앱의 `tests/` 패키지)
- 마이그레이션 누락 확인: `python manage.py makemigrations --check --dry-run`
- 데모 데이터: `python manage.py seed_demo` (admin/admin)

## 규칙
- 파이프라인 단계 변경은 반드시 `campaigns/services.py`의 `change_stage()`를 통한다 (StatusLog 기록, 연관 필드 동기화). `participation.stage = ...` 직접 대입 금지. 되돌리기 시 초기화 정책(지급일/업로드 일시/참여 의사)도 여기서 처리한다.
- 인플루언서 추가는 `services.add_to_campaign()` 사용 (멱등). 핸들은 `influencers.models.normalize_handle()`로 정규화.
- 대시보드/칸반용 조회 쿼리는 `campaigns/selectors.py`에 둔다.
- UI: Django 템플릿 + Tailwind(CDN) + HTMX. 부분 갱신 템플릿은 `_` 접두사(`_board.html`). SPA 도입하지 않음.
- 설정값/시크릿은 `.env` → `config/settings.py`의 `os.environ` 로 읽는다. 시크릿 파일은 `secrets/`(git 제외).
- 모델 필드 verbose_name·화면 문구는 한국어.
- 시트는 플랫폼 내 캠페인 시트가 원본(구글 시트 연동 없음). 고객사에는 엑셀/CSV 내보내기로 전달. 기본 열은 `sheets/columns.py`의 `COLUMNS` 한 곳에서 관리(화면·CSV·엑셀 공용), 고객사 파일에서 뺄 열은 `internal=True`. 구글 폼 "추가 답변" 열은 `survey_columns()`가 캠페인별로 붙인다.
- 설문은 구글 폼. 질문 편집은 구글 폼에서, 플랫폼은 `surveys/services.py`(`sync_form` → 매칭 → `apply_response`)로 가져와 옮겨 적는다. Google Forms API는 읽기 전용·서비스 계정. 답변 파싱/질문 제목 → 칸 추정은 `surveys/parsing.py`. 못 읽은 값은 기존 값을 덮어쓰지 않는다.
- 메시징 채널은 `messaging/providers/`에 Provider 클래스 1개 추가 + `PROVIDERS` 등록으로 확장. 발송은 `messaging.services.send_message()`(이력 기록·실패도 기록). 현재: 인스타 DM(Meta API 직접), Gmail(SMTP 앱 비밀번호, `MAILERS["gmail"]`, 발송만).
- 인스타 DM은 API로 먼저 보낼 수 없다(Meta 정책) → 첫 콜드 DM은 수동, 상대 마지막 메시지로부터 24시간 안에만 API 발송. 웹훅 `/hooks/instagram/`은 서명(X-Hub-Signature-256) 검증 필수.
- 외부 API 호출(Google Forms, Meta)은 `httpx`, 테스트에서는 fake client / `httpx.MockTransport`로 대체. 테스트에서 실제 네트워크 호출 금지.
