# PowerSeed — 작업 가이드

인플루언서 시딩 CRM (Django 6.1, Python 3.12+). 설계/로드맵: `docs/ROADMAP.md`. 진행 상황: `README.md`의 로드맵 체크리스트. **이어서 할 일·시작 명령: `docs/NEXT.md`** (작업을 마치면 갱신).

## 명령
- 테스트: `python manage.py test` (외부 API는 mock, 테스트는 각 앱의 `tests/` 패키지)
- 마이그레이션 누락 확인: `python manage.py makemigrations --check --dry-run`
- 데모 데이터: `python manage.py seed_demo` (admin/admin)

## 작업 방식
- `main` = 운영(푸시하면 Render 자동 배포). 기능·수정마다 `main`에서 브랜치(`feat/…`, `fix/…`, `chore/…`)를 새로 만들어 작업 → 테스트 통과·사용자 확인 후 `main`에 합치고 브랜치 삭제. `main`에 직접 커밋하지 않는다.
- 화면 이름·위치는 `docs/SCREENS.md` 기준(화면을 추가·변경하면 갱신). 사용자 불편 목록·할 일 후보는 `docs/BACKLOG.md`(처리하면 '완료'로 옮김).

## 규칙
- 캠페인은 유형(`Campaign.kind`) 방문형/배송형. 단계 목록은 `campaigns/models.py`의 `PIPELINES`·`EXIT_STAGES`(유형별) 한 곳에서 관리하고, 화면의 단계 선택지는 `campaign.stage_choices`를 쓴다(`Stage.choices` 전체를 보여 주지 않음). 같은 의미의 단계는 유형이 달라도 같은 값(업로드 완료·지급 완료 등).
- 파이프라인 단계 변경은 반드시 `campaigns/services.py`의 `change_stage()`를 통한다 (StatusLog 기록, 연관 필드 동기화, 캠페인 유형에 없는 단계 거부). `participation.stage = ...` 직접 대입 금지. 되돌리기 시 초기화 정책(지급일/지급 상태/업로드 일시/수령일/발송일/참여 의사)도 여기서 처리한다. 자동 단계 이동(설문 응답·설문 발송)은 대상 단계가 그 유형에 있을 때만.
- 인플루언서 추가는 `services.add_to_campaign()` 사용 (멱등, 블랙리스트면 ValidationError — 호출하는 쪽에서 처리). 핸들은 `influencers.models.normalize_handle()`로 정규화. 국가별 ID(`code`)는 저장 시 자동 부여.
- 대시보드/칸반용 조회 쿼리는 `campaigns/selectors.py`에 둔다.
- UI: Django 템플릿 + Tailwind(CDN) + HTMX. 부분 갱신 템플릿은 `_` 접두사(`_board.html`). SPA 도입하지 않음.
- 설정값/시크릿은 `.env` → `config/settings.py`의 `os.environ` 로 읽는다. 시크릿 파일은 `secrets/`(git 제외).
- 모델 필드 verbose_name·화면 문구는 한국어.
- 시트는 플랫폼 내 캠페인 시트가 원본(구글 시트 연동 없음). 고객사에는 엑셀/CSV 내보내기로 전달. 기본 열은 `sheets/columns.py`의 `COLUMNS` 한 곳에서 관리(화면·CSV·엑셀 공용), 고객사 파일에서 뺄 열은 `internal=True`, 유형 전용 열은 `kinds`. 시트 행 폼(`SheetRowForm`)은 열이 있는 필드만 남긴다(전송 안 된 필드를 빈 값으로 덮어쓰지 않도록). 구글 폼 "추가 답변" 열은 `survey_columns()`가 캠페인별로 붙인다.
- 다른 탭의 열 정의: 인플루언서 DB `influencers/columns.py`, 콘텐츠 성과 `performance/columns.py` (같은 `Column`, 내보내기는 `sheets.exports.export_response`).
- 비용·성과 계산: 참여 건 총비용(원)은 `performance.costs.CostBook` 한 곳에서 계산(참여 상세·콘텐츠 성과·리포트 공용) = 확정 원고료(원화만) + 제품 원가 + 배송비. 정산 탭(지급 내역·환율표)은 2026-11-28에 뺐다 — 외화 원고료는 비용에서 빠지고 경고로 표시. 계산 열(참여율·CPV·CPM·ROAS)과 리포트 집계는 `performance/selectors.py`, 저장하지 않는다.
- 설문은 구글 폼. 질문 편집은 구글 폼에서, 플랫폼은 `surveys/services.py`(`sync_form` → 매칭 → `apply_response`)로 가져와 옮겨 적는다. Google Forms API는 읽기 전용·서비스 계정. 답변 파싱/질문 제목 → 칸 추정은 `surveys/parsing.py`. 못 읽은 값은 기존 값을 덮어쓰지 않는다.
- 발굴(수집): `collector/services.py`. 수집 방법 3가지(Apify `adapters/apify.py` 2단계 비동기 — `start_job` → `poll_job`, 연결된 스크래퍼, insta-finder 파일 `importers.py`)는 모두 `finish_job()`을 지나며, 수집된 계정은 **곧바로 인플루언서 DB에 등록**(빈 칸만 채움, 카테고리는 작업 지정값 또는 `classify.guess_category()`). 캠페인 추가는 후보 검토에서 고른 것만(`approve_candidates`). Apify 상태 확인은 화면 HTMX 폴링 + cron `poll_collector_jobs` — 웹 요청 안에서 수집 완료를 기다리지 않는다.
- 메시징 채널은 `messaging/providers/`에 Provider 클래스 1개 추가 + `PROVIDERS` 등록으로 확장. 발송은 `messaging.services.send_message()`(이력 기록·실패도 기록). 현재: 인스타 DM(Meta API 직접), Gmail(SMTP 앱 비밀번호, `MAILERS["gmail"]`, 발송만).
- 인스타 DM은 API로 먼저 보낼 수 없다(Meta 정책) → 첫 콜드 DM은 인스타 앱에서 직접 보내고 `services.record_manual_message()`로 기록(`Message.manual`), 상대 마지막 메시지로부터 24시간 안에만 API 발송. 보낸 뒤 처리(마지막 연락일, 컨택 대상 → 컨택 완료, 설문 링크면 설문 발송)는 `_after_outbound()` 한 곳. 웹훅 `/hooks/instagram/`은 서명(X-Hub-Signature-256) 검증 필수.
- 외부 API 호출(Google Forms, Meta)은 `httpx`, 테스트에서는 fake client / `httpx.MockTransport`로 대체. 테스트에서 실제 네트워크 호출 금지.
