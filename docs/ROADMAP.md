# PowerSeed — 인플루언서 시딩 CRM MVP 아키텍처 & 로드맵

## Context
광고대행사의 시딩 업무(섭외 → 구글시트 기입 → 확정·원고료 협상 → 방문/업로드 추적 → 지급)가 전부 수작업·인스타 DM(98%)·구글시트에 흩어져 있음. 목표는 **해시태그 수집 → 컨택 → 설문 → 시트 자동기입 → 진행 트래킹 → 지급**을 하나의 Django 앱에서 End-to-End로 처리하는 MVP.

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
| 백그라운드 작업 | **Django 6 내장 `django.tasks`** (현재 ImmediateBackend, 배포 시 DB/큐 백엔드로 교체) | Redis 없이 시트 동기화·릴스 수집·웹훅 후처리 비동기화. 규모 커지면 Celery로 교체(인터페이스 동일) |
| 운영 UI | Django Admin(데이터 관리) + Django 템플릿 + **HTMX** + Tailwind(CDN) 칸반/대시보드 | SPA 없이 빠른 MVP |
| 설정 | `.env` + `config/settings.py` 내장 로더 | 키/시크릿 분리 |
| 구글 시트 | `gspread` + 서비스 계정 | 가장 단순·안정 |
| HTTP | `httpx` | 채널톡/수집 API 호출 |
| 배포 | Docker + Render/Fly.io (gunicorn + worker 프로세스 1개) | 채널톡 웹훅·설문 링크용 공개 HTTPS 필요 |

## 2. 아키텍처 (Django 앱 = 모듈)
```
config/            settings(env 분리), urls
core/              TimeStampedModel, 공용 choices, 대시보드
influencers/       Influencer(계정 마스터)
campaigns/         Client, Campaign, Participation(파이프라인 핵심), StatusLog
collector/         HashtagJob, Candidate + adapters/ (기존 수집기 래핑)  ← F1
messaging/         providers/{base.py, channeltalk.py}, Conversation, Message, Template, webhook view  ← F2
surveys/           토큰 기반 공개 설문 폼, SurveyResponse  ← F3
sheets/            SheetBinding, sync service(gspread)  ← F3
metrics/           ReelsSnapshot, monthly_reels_avg 계산 + fetcher 어댑터  ← F3
```
**데이터 흐름**
1. 해시태그 입력 → `collector` task가 어댑터 호출 → `Candidate` 적재 → 운영자 검토 화면에서 "컨택 대상으로" → `Influencer` upsert + `Participation(status=CONTACT_TARGET)` 생성.
2. 컨택: 채널톡 대화와 Participation 연결. 템플릿 메시지에 **개인화 설문 링크**(`/s/<uuid>/`) 삽입 후 발송.
3. 인플루언서 설문 제출 → Participation/Influencer 갱신 → 상태 `RESPONDED` → `sheets.sync_participation` task enqueue → 캠페인 시트 행 upsert.
4. `metrics` task가 릴스 데이터 수집 → `monthly_reels_avg` 자동 갱신 → 시트 반영.
5. 협상·확정·방문·업로드·지급은 칸반/Admin에서 상태 전이, 모든 변경 `StatusLog` 기록 + 시트 반영.

**채널 추상화 (F2)** — 과도한 추상화 없이 Provider 1개 인터페이스만:
```python
class MessagingProvider(Protocol):
    key: str                                   # "channeltalk", 추후 "instagram", "gmail", "kakao", "line"
    def send_message(self, conversation, text: str) -> ExternalMessageRef: ...
    def parse_webhook(self, request) -> list[InboundEvent]: ...
    def verify_webhook(self, request) -> bool: ...
```
`PROVIDERS = {"channeltalk": ChannelTalkProvider}` 레지스트리, 웹훅 URL `/hooks/<provider>/`. 신규 채널 = 클래스 1개 추가.

> ⚠️ 제약: Meta 정책상 **인스타 DM은 API로 '먼저' 보낼 수 없음**(상대가 먼저 메시지한 대화 + 24시간 창 내만 가능). 채널톡도 동일 제약을 받으므로 **최초 콜드 DM은 운영자가 수동 발송**, 이후 답장 대화부터 플랫폼에서 템플릿/설문 링크 발송·수신 기록. 이 전제를 MVP에 반영.

## 3. DB 스키마 (핵심 모델)
**Influencer** (계정 마스터, 캠페인 무관)
- `account_name`, `platform`(instagram/youtube/tiktok/blog…), `instagram_handle`(unique, 소문자 정규화), `account_url`, `follower_count`
- `monthly_reels_avg`(int, null), `reels_avg_updated_at`, `reels_avg_source`(auto/survey/manual)
- `notes`, `special_notes`, `source`(collector/manual/survey), `discovered_hashtags`(JSON), `owner`(FK User), timestamps

**Client / Campaign**
- Client: `name`, `contact`, `notes`
- Campaign: `client`, `name`, `guideline`(text/url), `visit_location`, `start_date`, `end_date`, `budget`, `default_fee`, `manager`(FK User), `sheet_id`/`worksheet_name`, `status`

**Participation** (캠페인 × 인플루언서, 파이프라인 1행 = 시트 1행)
- `campaign`, `influencer` (unique_together), `assignee`(FK User), `conversation`(FK, null)
- `stage`: `CONTACT_TARGET → CONTACTED → SURVEY_SENT → RESPONDED → NEGOTIATING → CONFIRMED → VISIT_SCHEDULED → VISITED → UPLOADED → PAYOUT_PENDING → PAID` / `DECLINED`, `DROPPED`
- `participation_status`(참여/불참/검토중/미응답)
- `available_visit_dates`(JSON 날짜 리스트), `confirmed_visit_at`(datetime)
- `fee_requested`, `fee_amount`(확정 원고료), `payout_method`(계좌이체/사업자 세금계산서/페이팔/기타), `payout_status`(미지급/지급대기/지급완료), `paid_at`
- `upload_due_at`, `upload_url`, `uploaded_at`
- `survey_token`(UUID), `survey_submitted_at`, `sheet_row_synced_at`
- `notes`, `special_notes`, timestamps
- (송금 계좌 등 민감정보는 MVP에서 시트에 쓰지 않음)

**StatusLog**: `participation`, `from_stage`, `to_stage`, `changed_by`, `memo`, `created_at` (중간관리자 진행 파악용)

**collector**: `HashtagJob`(hashtag, status, requested_by, result_count, error) / `Candidate`(job, handle, account_url, follower_count, raw JSON, review_status: pending/approved/rejected)

**messaging**: `ChannelAccount`(provider, external_id, 표시명 — 다중 인스타 계정) / `Conversation`(provider, external_id, channel_account, influencer, last_message_at) / `Message`(conversation, direction in/out, text, external_id, sent_by, created_at) / `MessageTemplate`(name, body with `{{survey_link}}` 등 변수)

**surveys**: `SurveyResponse`(participation, payload JSON 원본, submitted_at, ip) — 정규화 값은 Participation/Influencer에 반영

**metrics**: `ReelsSnapshot`(influencer, media_id, posted_at, view_count, like_count, comment_count, fetched_at)

## 4. 구글 시트 스키마 (캠페인당 1 워크시트, DB가 원본 → 시트로 단방향 upsert)
| 열 | 소스 |
|---|---|
| ID (participation id, 행 매칭 키) | Participation.id |
| 계정 이름 / 플랫폼 / 인스타 계정 / 계정 URL / 팔로워 수 | Influencer |
| 한 달 릴스 평균 (+갱신일) | Influencer.monthly_reels_avg (자동) |
| 참여 의사 / 방문 가능일 | Participation |
| 원고료 / 송금 수단 | Participation.fee_amount / payout_method |
| 비고 / 특이사항 | Participation.notes / special_notes |
| 진행 단계 / 담당자 / 확정 방문일시 / 업로드 URL / 지급 상태 / 지급일 / 설문 제출일 | Participation |

열 정의는 `sheets/columns.py`의 단일 매핑 리스트로 관리(헤더 자동 생성). ID 열로 행 검색 후 update, 없으면 append. 실패 시 task 재시도 + `sheet_row_synced_at` 미갱신으로 재동기화 대상 표시.

## 5. 설문 (F3)
- 공개 URL `/s/<survey_token>/` (로그인 불필요, 토큰 = 인증). 기존 값 prefill.
- 항목: 계정 이름, 인스타 계정, 계정 URL, 팔로워 수, 참여 의사, 방문 가능일(다중 날짜 선택), 희망 원고료, 송금 수단, 비고/특이사항. (릴스 평균은 자동 산출이라 설문에서 제외, 필요 시 "본인 기입" 보조 항목)
- 제출 → 트랜잭션으로 반영 → stage `RESPONDED` → 시트 동기화 task. 재제출 허용(마감 후 잠금).

## 6. 한 달 릴스 평균 (F3)
- `metrics/fetchers/` 어댑터 인터페이스 `fetch_recent_reels(handle) -> list[ReelData]`
- 계산 함수 `compute_monthly_reels_avg(snapshots, window_days=30)` — 기준은 질문 답변에 따라 확정 (기본안: 최근 30일 내 릴스의 평균 조회수, 30일 내 0건이면 최근 N개 평균으로 fallback, 표본 수도 함께 저장)
- 트리거: 컨택 대상 승격 시 + 주기적(일 1회) + 수동 "재계산" 버튼.

---

## 7. 구현 로드맵
**Phase 0 — 기반 정리 (0.5일)** ✅ 완료
- `.gitignore` 추가, `__pycache__`/`db.sqlite3` 추적 해제, 루트 `models.py`·`seed.py` 제거
- `.env` 로더 도입(SECRET_KEY, DEBUG, DB, 채널톡/구글 키), `ko-kr` / `Asia/Seoul`, `requirements.txt`
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

**Phase 3 — 설문 + 구글 시트 동기화 (2일)**
- 공개 설문 폼/검증/반영, 링크 생성·복사 버튼
- `django-tasks` 워커, gspread 서비스 계정 연동, 캠페인 시트 바인딩, upsert 동기화 + 수동 "전체 재동기화"
- ✅ 설문 제출 → DB 반영 → 테스트 시트 행 생성/갱신 확인 (sheets는 mock 단위테스트 + 실제 시트 수동 확인)

**Phase 4 — 해시태그 수집기 편입 (1~2일, 기존 코드 수령 후)**
- 기존 수집기를 `collector/adapters/`로 래핑 → HashtagJob task → Candidate 적재
- 후보 검토 화면(필터·일괄 승인) → Influencer upsert(handle 기준 중복 제거) + Participation 생성
- ✅ 해시태그 입력 → 후보 목록 → 승격까지 E2E

**Phase 5 — 채널톡 연동 (2~3일)**
- `MessagingProvider` 베이스 + ChannelTalkProvider(Open API v5: 메시지 발송, 웹훅 수신·서명 검증)
- 웹훅 → Conversation/Message 저장, 인스타 핸들로 Influencer 자동 매칭(실패 시 수동 연결 UI)
- Participation 화면에서 대화 이력 보기 + 템플릿(설문 링크 포함) 발송 → stage `SURVEY_SENT`
- ✅ 채널톡 테스트 채널로 수신/발신 왕복, 단위테스트는 httpx mock

**Phase 6 — 릴스 평균 자동 산출 (1~2일)**
- fetcher 어댑터(수집기 재사용 or 외부 API), ReelsSnapshot 저장, 계산·주기 task, 시트 반영
- ✅ 고정 fixture로 계산 로직 테스트 + 실계정 1~2개 수동 확인

**Phase 7 — 배포 (1일)**
- Dockerfile, PostgreSQL, gunicorn + task worker, HTTPS 도메인, 채널톡 웹훅 URL 등록
- ✅ 운영 URL에서 E2E 시나리오 1회 (수집→컨택→설문→시트→확정→업로드→지급)

**후순위(MVP 이후)**: 인스타 DM 직접 연동/Gmail/카카오/LINE provider, 지급 일괄 처리·정산 리포트, 업로드 게시물 성과 추적, 권한 세분화, 시트→DB 역동기화.

## 8. 검증 방법 (공통)
- `python manage.py test` (모델/서비스/설문/시트 매핑/릴스 계산/웹훅 파서 — 외부 API는 mock)
- `python manage.py runserver` + worker 실행 후 브라우저 E2E 시나리오
- 실제 연동(시트·채널톡)은 테스트용 시트/채널로 수동 확인

## 9. 확정된 결정 (사용자 답변)
- 릴스 평균 = **최근 30일 내 릴스의 평균 조회수** (0건이면 최근 12개 평균 fallback, 표본 수·기준일 함께 저장)
- 수집기 = **Python 스크래핑 스크립트** → `collector/adapters/scraper.py`로 래핑, 동일 스크래퍼를 `metrics` fetcher(릴스 조회수 수집)에도 재사용. 스크래핑은 차단/속도 제한 대비 job 단위 재시도·딜레이 설정 포함
- 시트 = **DB 원본 → 시트 단방향 upsert**

## 10. 단계별로 필요한 자료 (해당 Phase 시작 전까지)
1. Phase 4: 수집기 코드를 레포 `collector/vendor/`(또는 경로 안내)로 제공 + 출력 필드
2. Phase 3: 구글 서비스 계정 JSON + 대상 스프레드시트를 서비스 계정 이메일에 공유
3. Phase 5: 채널톡 Access Key/Secret, 연결 인스타 계정 목록, 웹훅 설정 권한
→ Phase 0~2는 위 자료 없이 바로 착수 가능
