# PowerSeed — 작업 가이드

인플루언서 시딩 CRM (Django 6.1, Python 3.12+). 설계/로드맵: `docs/ROADMAP.md`. 진행 상황: `README.md`의 로드맵 체크리스트.

## 명령
- 테스트: `python manage.py test` (외부 API는 mock, 테스트는 각 앱의 `tests/` 패키지)
- 마이그레이션 누락 확인: `python manage.py makemigrations --check --dry-run`
- 데모 데이터: `python manage.py seed_demo` (admin/admin)

## 규칙
- 파이프라인 단계 변경은 반드시 `campaigns/services.py`의 `change_stage()`를 통한다 (StatusLog 기록, 연관 필드 동기화). `participation.stage = ...` 직접 대입 금지.
- 인플루언서 추가는 `services.add_to_campaign()` 사용 (멱등). 핸들은 `influencers.models.normalize_handle()`로 정규화.
- 대시보드/칸반용 조회 쿼리는 `campaigns/selectors.py`에 둔다.
- UI: Django 템플릿 + Tailwind(CDN) + HTMX. 부분 갱신 템플릿은 `_` 접두사(`_board.html`). SPA 도입하지 않음.
- 설정값/시크릿은 `.env` → `config/settings.py`의 `os.environ` 로 읽는다. 시크릿 파일은 `secrets/`(git 제외).
- 모델 필드 verbose_name·화면 문구는 한국어.
- 구글 시트는 DB → 시트 단방향. 시트 열 정의는 `sheets/columns.py` 한 곳에서 관리(Phase 3).
- 새 메시징 채널은 `messaging/providers/`에 Provider 클래스 1개 추가로 확장(Phase 5).
- 인스타 DM은 API로 먼저 보낼 수 없다(Meta 정책) → 첫 콜드 DM은 수동, 이후 대화부터 자동화.
