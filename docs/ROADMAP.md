# PowerSeed — 인플루언서 시딩 CRM MVP 아키텍처 & 로드맵

## Context
광고대행사의 시딩 업무(섭외 → 구글시트 기입 → 확정·원고료 협상 → 방문/업로드 추적 → 지급)가 전부 수작업·인스타 DM(98%)·구글시트에 흩어져 있음. 목표는 **해시태그 수집 → 컨택 → 설문 → 시트 자동기입 → 진행 트래킹 → 지급**을 하나의 Django 앱에서 End-to-End로 처리하는 MVP.

**운영 방식 (2026-11-23 확정)**
- 시트는 **플랫폼 안의 캠페인 시트**가 원본이다. 구글 시트 연동은 하지 않는다.
- 사내에서는 플랫폼에서 관리하고, 고객사에는 **최종본만 엑셀/CSV로 내려받아 전달**한다.
- 설문은 **구글 폼**으로 만든다. 질문 추가·수정은 구글 폼에서 하고, 플랫폼은 Google Forms API로 질문·응답을 가져와 캠페인 시트에 옮겨 적는다(주기능).
- 연락 채널은 **인스타 DM(Meta API 직접 연동)** + **Gmail(발송만)**. 채널톡은 쓰지 않는다.

### 착수 시점 레포 상태 (2026-11-20, 정리 완료)
- Django 6.1.3 / `.venv` Python 3.15, 의존성은 Django만 설치됨. DB는 빈 `db.sqlite3`.
- `core` 앱은 생성만 됐고 **`INSTALLED_APPS`에 미등록**, `core/models.py` 비어있음.
- 루트의 `models.py`(Influencer 초안)는 잘못된 위치 → 앱으로 이전 후 삭제. `seed.py`는 빈 파일.
- `.gitignore` 없음 → `__pycache__`, `db.sqlite3`가 커밋됨. `SECRET_KEY` 하드코딩, `TIME_ZONE='UTC'`.
- 해시태그 수집기 코드는 레포에 없음 (`C:\dev\powerseed`는 이 레포의 구버전 사본).
- README는 CP949/UTF-8 깨짐 → UTF-8로 재작성.

---

## 1. 추천 기술 스택
| 영역 | 선택 | 이유 |
|---|---|---|
| 백엔드 | Django 6.1 (기존 유지) | 이미 세팅됨, Admin으로 운영 화면 즉시 확보 |
| DB | dev: SQLite → 운영: PostgreSQL | JSONField·동시성, 배포 시 전환 |
| 백그라운드 작업 | **Django 6 내장 `django.tasks`** (현재 ImmediateBackend, 배포 시 DB/큐 백엔드로 교체) | Redis 없이 해시태그 수집·릴스 수집·웹훅 후처리 비동기화. 규모 커지면 Celery로 교체(인터페이스 동일) |
| 운영 UI | Django Admin(데이터 관리) + Django 템플릿 + **HTMX** + Tailwind(CDN) 칸반/대시보드 | SPA 없이 빠른 MVP |
| 설정 | `.env` + `config/settings.py` 내장 로더 | 키/시크릿 분리 |
| 캠페인 시트 | 플랫폼 내 표 화면(HTMX 행 수정) + `openpyxl` 엑셀 / 표준 `csv` 내보내기 | 외부 동기화 없이 DB가 곧 시트, 고객사에는 파일 전달 |
| 설문 | **구글 폼** + Google Forms API v1(서비스 계정, `google-auth`) | 질문 편집은 구글 폼이 가장 쉬움, 플랫폼은 읽기 전용으로 가져와 옮겨 적기 |
| 메시징 | 인스타: Meta Instagram API(Instagram 로그인 방식) 직접 / Gmail: SMTP + 앱 비밀번호(`MAILERS["gmail"]`) | 채널톡 비용 없음, Gmail은 발송만 필요 |
| HTTP | `httpx` | Google Forms / Meta Graph API 호출 (테스트는 MockTransport) |
| 배포 | Docker + Render/Fly.io (gunicorn + worker 프로세스 1개) + cron(`sync_google_forms`) | Meta 웹훅용 공개 HTTPS 필요 |

## 2. 아키텍처 (Django 앱 = 모듈)
```
config/            settings(env 분리), urls
core/              TimeStampedModel, 공용 choices, 대시보드
influencers/       Influencer(계정 마스터)
campaigns/         Client, Campaign, Participation(파이프라인 핵심), StatusLog
collector/         HashtagJob, Candidate + adapters/ (기존 수집기 래핑)  ← F1
messaging/         providers/{base.py, instagram.py, gmail.py}, InstagramThread, Message, MessageTemplate, /hooks/<provider>/  ✅
sheets/            캠페인 시트 화면 + 엑셀/CSV 내보내기, 열 정의 columns.py (모델 없음)  ✅
surveys/           구글 폼 연동: CampaignForm, FormQuestion(질문→칸 매핑), FormResponse, sync/apply 서비스  ✅
metrics/           ReelsSnapshot, monthly_reels_avg 계산 + fetcher 어댑터  ← F3
```
**데이터 흐름**
1. 해시태그 입력 → `collector` task가 어댑터 호출 → `Candidate` 적재 → 운영자 검토 화면에서 "컨택 대상으로" → `Influencer` upsert + `Participation(status=CONTACT_TARGET)` 생성.
2. 컨택: 첫 인스타 DM은 운영자가 앱에서 수동 발송(웹훅 에코로 이력 기록) → 상대 답장이 웹훅으로 들어오면 IGSID를 인스타 계정명으로 Influencer와 연결 → 24시간 안에 플랫폼에서 템플릿 메시지 발송. 이메일이 있으면 Gmail로도 발송. 메시지에 **개인 설문 링크**(구글 폼 + 참여 코드 미리 채움)가 들어가면 stage `SURVEY_SENT`.
3. 인플루언서가 구글 폼 제출 → `sync_google_forms`(cron) 또는 "질문·응답 가져오기" 버튼 → 참여 코드/인스타 계정으로 Participation 매칭 → 매핑된 칸에 옮겨 적기 + 추가 답변은 `form_answers` → stage `RESPONDED` → 캠페인 시트에 바로 보임.
4. `metrics` task가 릴스 데이터 수집 → `monthly_reels_avg` 자동 갱신.
5. 협상·확정·방문·업로드·지급은 칸반/시트/참여 상세에서 상태 전이, 모든 변경 `StatusLog` 기록.
6. 캠페인 마무리 시 시트에서 **고객사 전달용 엑셀/CSV** 다운로드 → 고객사 전달.

**채널 추상화 (F2)** — `messaging/providers/base.py`:
```python
class MessagingProvider:
    channel: str                 # "instagram", "email" — 추후 "kakao", "line"
    supports_subject: bool
    def is_configured(self) -> bool: ...
    def recipient(self, participation) -> str: ...
    def unavailable_reason(self, participation) -> str | None: ...   # 보낼 수 없으면 이유 (24시간 창, 이메일 없음 등)
    def send(self, participation, *, subject, body) -> str: ...      # 외부 메시지 ID, 실패 시 ProviderError
```
`PROVIDERS = {"instagram": InstagramProvider, "email": GmailProvider}` 레지스트리, 웹훅 URL `/hooks/<provider>/`(현재 instagram). 신규 채널 = 클래스 1개 추가.

> ⚠️ 제약: Meta 정책상 **인스타 DM은 API로 '먼저' 보낼 수 없음**(상대가 보낸 마지막 메시지로부터 24시간 이내만 가능). **최초 콜드 DM은 운영자가 인스타 앱에서 수동 발송**, 이후 답장 대화부터 플랫폼에서 템플릿/설문 링크 발송·수신 기록. Meta 앱 검수(`instagram_business_manage_messages`)와 비즈니스/크리에이터 계정이 필요.

## 3. DB 스키마 (핵심 모델)
**Influencer** (계정 마스터, 캠페인 무관)
- `account_name`, `platform`(instagram/youtube/tiktok/blog…), `instagram_handle`(unique, 소문자 정규화·형식 검증), `account_url`, `email`(Gmail 발송 대상), `follower_count`
- `monthly_reels_avg`(int, null), `reels_avg_updated_at`, `reels_avg_source`(auto/survey/manual)
- `notes`, `special_notes`, `source`(collector/manual/survey), `discovered_hashtags`(JSON), `owner`(FK User), timestamps

**Client / Campaign**
- Client: `name`, `contact`, `notes`
- Campaign: `client`, `name`, `guideline`(text/url), `visit_location`, `start_date`, `end_date`, `budget`, `default_fee`, `manager`(FK User), `status`

**Participation** (캠페인 × 인플루언서, 파이프라인 1건 = 캠페인 시트 1행)
- `campaign`, `influencer` (unique_together), `assignee`(FK User)
- `stage`: `CONTACT_TARGET → CONTACTED → SURVEY_SENT → RESPONDED → NEGOTIATING → CONFIRMED → VISIT_SCHEDULED → VISITED → UPLOADED → PAYOUT_PENDING → PAID` / `DECLINED`, `DROPPED`
- `participation_status`(참여/불참/검토중/미응답)
- `available_visit_dates`(JSON 날짜 리스트), `confirmed_visit_at`(datetime)
- `fee_requested`, `fee_amount`(확정 원고료), `payout_method`(계좌이체/사업자 세금계산서/페이팔/기타), `payout_status`(미지급/지급대기/지급완료), `paid_at`
- `upload_due_at`, `upload_url`, `uploaded_at`
- `survey_token`(UUID — 구글 폼 "참여 코드"로 미리 채움), `survey_submitted_at`, `form_answers`(JSON — 구글 폼 추가 답변 {질문 ID: 답})
- `notes`, `special_notes`, timestamps
- (송금 계좌 등 민감정보는 MVP에서 시트·내보내기에 넣지 않음)

**StatusLog**: `participation`, `from_stage`, `to_stage`, `changed_by`, `memo`, `created_at` (중간관리자 진행 파악용)

**collector**: `HashtagJob`(hashtag, status, requested_by, result_count, error) / `Candidate`(job, handle, account_url, follower_count, raw JSON, review_status: pending/approved/rejected)

**messaging**: `MessageTemplate`(name, channel, subject, body — 변수 `{{이름}} {{계정}} {{캠페인}} {{방문장소}} {{설문링크}}`) / `InstagramThread`(igsid unique, username, influencer, last_inbound_at — 24시간 창 판단) / `Message`(channel, direction in/out, status sent/failed/received, influencer, participation, thread, recipient, subject, body, error, external_id, sent_by, created_at)

**surveys**: `CampaignForm`(campaign 1:1, form_id, title, responder_uri, synced_at, last_error) / `FormQuestion`(form, question_id, title, kind, options, position, target=옮겨 적을 칸, include_in_client_export, is_active) / `FormResponse`(form, response_id, participation, match_method code/handle/manual, answers JSON 원본, respondent_handle, submitted_at, applied_at)

**metrics**: `ReelsSnapshot`(influencer, media_id, posted_at, view_count, like_count, comment_count, fetched_at)

## 4. 캠페인 시트 (플랫폼 내, DB가 곧 시트)
- 화면 `/campaigns/<id>/sheet/`: 인플루언서 1명 = 1행. 단계·담당자·거절/이탈 제외 필터, 행 단위 HTMX 수정(단계 변경은 `change_stage()` 경유)
- 내보내기 `/campaigns/<id>/export.xlsx|csv?scope=client|internal` — 현재 필터 기준
  - `client`(기본): 고객사 전달용, `internal=True` 열 제외 / `internal`: 사내용 전체 열
  - 엑셀: 헤더 고정·자동 필터·숫자/날짜 서식, CSV: UTF-8 BOM. 수식 주입 방지(`=`, `+`, `-`, `@` 시작 값은 글자로)
- 열 정의는 `sheets/columns.py`의 `COLUMNS` 단일 리스트 (화면·CSV·엑셀 공용) + 캠페인별 구글 폼 "추가 답변" 열이 뒤에 자동으로 붙음(`survey_columns`)

| 열 | 소스 | 고객사 파일 |
|---|---|---|
| 인스타 계정 / 계정 이름 / 플랫폼 / 계정 URL / 팔로워 수 / 한 달 릴스 평균 | Influencer | ✅ |
| 진행 단계 / 참여 의사 / 방문 가능일 / 확정 방문 일시 | Participation | ✅ |
| 원고료 / 송금 수단 / 지급 상태 / 지급일 | Participation | ✅ |
| 업로드 기한 / 업로드 URL / 업로드 일시 / 특이사항 | Participation | ✅ |
| 희망 원고료 / 이메일 / 설문 제출일 / 담당자 / 비고 | Participation·Influencer | 사내용만 |
| 구글 폼 추가 답변 (질문마다 1열) | Participation.form_answers | 질문별 "고객사 파일" 체크 |

## 5. 설문 (F3) — 구글 폼 연동
- **질문 추가·수정은 구글 폼에서.** 플랫폼은 Google Forms API(읽기 전용, 서비스 계정)로 질문·응답을 가져와 옮겨 적는다.
- 연결: 캠페인 설문 화면에 폼 편집 주소(`/forms/d/<id>/edit`) 입력. 폼은 서비스 계정 이메일을 편집자로 공유해야 함.
- 질문 → 칸 매핑(`FormQuestion.target`): 새 질문은 제목 키워드로 자동 추정(`surveys/parsing.py: guess_target`), 화면에서 수정. 한 칸엔 질문 하나. 나머지는 "추가 답변" → 시트 열.
- 응답자 매칭: ① "참여 코드" 질문(개인 링크 `?usp=pp_url&entry.<질문ID 16진수→10진수>=<survey_token>`으로 미리 채움) ② "인스타 계정" 답변(정규화 후 캠페인 내 검색) ③ 실패 시 화면에서 수동 연결 / 응답자 계정으로 새로 추가.
- 옮겨 적기(`apply_response`): 금액·날짜·참여 의사·송금 수단 자유 입력 파싱, 못 읽으면 기존 값 유지. 열린 건만 stage `RESPONDED`로, 종료 건은 단계·참여 의사 유지.
- 동기화: 매번 전체 응답을 가져와 `lastSubmittedTime`이 바뀐 응답만 다시 반영(응답 수정 지원). 수동 버튼 + `manage.py sync_google_forms`(cron 권장 10분). 매핑 변경 후 "전체 다시 반영"은 API 호출 없이 저장된 응답으로.
- 미확인: 미리 채우기 entry 번호 = 질문 ID(16진수)의 10진수 값이라는 규칙은 실제 폼으로 확인 필요(틀리면 코드 자동 입력만 안 되고 인스타 계정 매칭은 동작).

## 6. 한 달 릴스 평균 (F3)
- `metrics/fetchers/` 어댑터 인터페이스 `fetch_recent_reels(handle) -> list[ReelData]`
- 계산 함수 `compute_monthly_reels_avg(snapshots, window_days=30)` — 기준은 질문 답변에 따라 확정 (기본안: 최근 30일 내 릴스의 평균 조회수, 30일 내 0건이면 최근 N개 평균으로 fallback, 표본 수도 함께 저장)
- 트리거: 컨택 대상 승격 시 + 주기적(일 1회) + 수동 "재계산" 버튼.

---

## 7. 구현 로드맵
**Phase 0 — 기반 정리 (0.5일)** ✅ 완료
- `.gitignore` 추가, `__pycache__`/`db.sqlite3` 추적 해제, 루트 `models.py`·`seed.py` 제거
- `.env` 로더 도입(SECRET_KEY, DEBUG, DB, 외부 연동 키), `ko-kr` / `Asia/Seoul`, `requirements.txt`
- 앱 생성·등록, base 템플릿(Tailwind+HTMX), 로그인
- ✅ `python manage.py check` / `migrate` 성공

**Phase 1 — 핵심 모델 + Admin (1~2일)** ✅ 완료
- influencers, campaigns(Participation, StatusLog) 모델·마이그레이션·Admin(list_filter, search, inline)
- 상태 전이 서비스 `campaigns/services.py: change_stage()` (StatusLog 기록 단일 진입점)
- ✅ 모델 단위 테스트, Admin에서 캠페인·참여자 CRUD

**Phase 2 — 운영 화면 (2일)** ✅ 완료
- 캠페인 상세: 단계별 칸반/테이블(HTMX 상태 변경, 원고료·방문일 인라인 수정), 담당자 필터
- 중간관리자 대시보드: 캠페인별 단계 집계, 지연(방문일 경과·업로드 미완료) 목록
- ✅ 브라우저에서 섭외→지급 전 단계 수동 전이

**Phase 3 — 캠페인 시트 + 구글 폼 연동 (2일)** ✅ 코드 완료
- 플랫폼 내 캠페인 시트(필터·행 수정) + 엑셀/CSV 내보내기(고객사용/사내용), 구글 시트 관련 필드·설정 제거
- 구글 폼 연결·질문 매핑·응답 매칭·옮겨 적기, 개인 설문 링크, 추가 답변 시트 열, `sync_google_forms` 명령
- ✅ 단위테스트(Forms API는 fake client) / ⏳ 실제 구글 폼으로 연결·응답 반영·미리 채우기 링크 확인

**Phase 4 — 해시태그 수집기 편입 (1~2일)** ✅ 코드 완료
- `collector/adapters/` 경계(`COLLECTOR_SCRAPER`로 기존 수집기 연결) → HashtagJob task → Candidate 적재
- 후보 검토 화면(필터·일괄 승인) → Influencer upsert(handle 기준 중복 제거) + Participation 생성
- ✅ 가짜 스크래퍼로 해시태그 입력 → 후보 목록 → 승격까지 E2E 테스트 / ⏳ 기존 수집기 코드 수령 후 실제 수집 확인

**Phase 5 — 메시징: 인스타 DM(Meta API) + Gmail (2~3일)** ✅ 코드 완료
- `MessagingProvider` 베이스 + InstagramProvider(발송, 24시간 창 검사, 웹훅 확인·서명 검증·수신/에코 저장, IGSID→계정명 매칭) + GmailProvider(SMTP 앱 비밀번호, 발송만)
- 참여 상세에서 채널 선택·템플릿·발송, 메시지 이력, 설문 링크 포함 시 stage `SURVEY_SENT`. 미연결 대화는 Admin에서 인플루언서 지정
- ✅ 단위테스트(httpx MockTransport, locmem 메일) / ⏳ Meta 앱 검수 후 실제 계정으로 수신·발신 왕복, Gmail 실제 발송 확인

**Phase 6 — 릴스 평균 자동 산출 (1~2일)**
- fetcher 어댑터(수집기 재사용 or 외부 API), ReelsSnapshot 저장, 계산·주기 task
- ✅ 고정 fixture로 계산 로직 테스트 + 실계정 1~2개 수동 확인

**Phase 7 — 배포 (1일)** 🔧 설정 완료, 실제 배포 전 (`docs/DEPLOY.md`)
- Dockerfile, `render.yaml`, PostgreSQL, gunicorn, cron(`sync_google_forms`), HTTPS, Meta 웹훅 URL 등록
- task worker는 수집기 연결 시 도입 (수집기 보류, 2026-11-24)
- ✅ 운영 URL에서 E2E 시나리오 1회 (수집→컨택→설문→시트→확정→업로드→지급→고객사용 엑셀 다운로드)

**후순위(MVP 이후)**: Gmail 답장 수신(Gmail API), 카카오/LINE provider, 인스타 7일 Human Agent 태그, 지급 일괄 처리·정산 리포트, 업로드 게시물 성과 추적, 권한 세분화, 고객사 열람용 읽기 전용 링크(파일 전달 대신).

## 8. 검증 방법 (공통)
- `python manage.py test` (모델/서비스/설문/시트·내보내기/릴스 계산/웹훅 파서 — 외부 API는 mock)
- `python manage.py runserver` + worker 실행 후 브라우저 E2E 시나리오
- 실제 연동(구글 폼·Meta·Gmail)은 테스트 폼/계정으로 수동 확인, 내보낸 엑셀은 엑셀/구글 시트에서 열어 확인

## 9. 확정된 결정 (사용자 답변)
- 릴스 평균 = **최근 30일 내 릴스의 평균 조회수** (0건이면 최근 12개 평균 fallback, 표본 수·기준일 함께 저장)
- 수집기 = **Python 스크래핑 스크립트** → `collector/adapters/scraper.py`로 래핑, 동일 스크래퍼를 `metrics` fetcher(릴스 조회수 수집)에도 재사용. 스크래핑은 차단/속도 제한 대비 job 단위 재시도·딜레이 설정 포함
- 시트 = **플랫폼 내 캠페인 시트가 원본**, 고객사에는 최종본 엑셀/CSV 전달 (구글 시트 연동 없음, 2026-11-23)
- 설문 = **구글 폼 연동** — 캠페인마다 구글 폼에서 질문 추가·수정, 플랫폼은 응답을 가져와 옮겨 적기가 주기능 (2026-11-23)
- 메시징 = **인스타 DM은 Meta API 직접 연동**, **Gmail은 발송만**(SMTP 앱 비밀번호). 채널톡 미사용 (2026-11-23)
- 재오픈 정책 = 지급 완료 이전 단계로 되돌리면 지급일 삭제 / 지급 대기 이전으로 되돌리면 지급 상태 미지급 / 업로드 완료 이전 단계로 되돌리면 업로드 일시 삭제 / 거절에서 재오픈하면 참여 의사 미응답
- 고객사 전달 파일 제외 열 = 희망 원고료 · 이메일 · 설문 제출일 · 담당자 · 비고

## 10. 단계별로 필요한 자료 (해당 Phase 시작 전까지)
1. Phase 4: 수집기 코드를 레포 `collector/vendor/`(또는 경로 안내)로 제공 + 출력 필드
2. Phase 3 실연동: 구글 서비스 계정 JSON(Forms API 사용 설정) + 테스트 구글 폼
3. Phase 5 실연동: Meta 개발자 앱 + 인스타 비즈니스/크리에이터 계정 + 앱 검수 + 공개 HTTPS(로컬은 터널), Gmail 앱 비밀번호
→ Phase 0~2는 위 자료 없이 바로 착수 가능
