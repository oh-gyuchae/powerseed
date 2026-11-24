# 이어서 작업하기

마지막 갱신: 2026-11-24. 작업 기준 브랜치는 `main`입니다. 할 일을 끝내면 이 문서를 함께 갱신합니다.

## 1. 작업 시작 명령 (Windows PowerShell)

### 이 저장소가 이미 있는 PC
```powershell
cd C:\dev\powerseed
.\start.ps1            # 최신 코드 받기 → 가상환경 → 패키지·DB → 서버 실행
.\start.ps1 -NoServer  # 서버 없이 작업 준비만
```
커밋하지 않은 변경이 있으면 코드를 받지 않고 경고만 표시합니다.

### 새 PC
```powershell
git clone https://github.com/oh-gyuchae/powerseed.git
cd powerseed
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

- 로컬 주소: http://127.0.0.1:8000 (`seed_demo` 계정 admin / admin, 로컬 전용)
- `.env`, `secrets/`, `db.sqlite3`는 git에 없으므로 PC마다 따로 준비합니다.
- 전역 `python`이 동작하지 않는 PC가 있으니 venv를 먼저 켭니다.

## 2. 현재 상태

| 항목 | 상태 |
|---|---|
| Phase 0~3, 5 | 코드 완료. 구글 폼·Gmail·인스타 DM은 실제 계정 연결 전 |
| Phase 4 수집기 | 구조만 완료. **실제 스크래퍼 연결 보류** |
| Phase 6 릴스 평균 | **보류** (데이터 수집 방식 결정 후. 고정 게시물 제외 반영 예정) |
| Phase 8 캠페인 유형·해외 탭 | 커밋·푸시 완료 (`be625c2`). 운영 화면 확인·환율 입력 전 |
| Phase 7 배포 | https://powerseed-web.onrender.com 가동, 관리자 로그인 확인 |
| Render 배포 브랜치 | `main` (2026-11-24 전환). `main` 푸시마다 자동 배포 |

## 3. 다음 할 일 (순서대로)

- [ ] **버그 수정 (`fix/payments-review` 브랜치 새로 만들어서):** 2026-11-24 코드 리뷰에서 나온 10건. 목록은 [BACKLOG.md](BACKLOG.md) "버그" 절. 정산 3건(환율 재계산·통화 변경·음수 입력) 먼저. 실제 정산 데이터 넣기 전에 끝낸다
- [ ] **(선택) Phase 1~5 코드 리뷰:** 2026-11-24 리뷰는 Phase 8 변경분만 봤다
- [ ] **Phase 8 확인·배포:** 로컬에서 `python manage.py migrate` → `seed_demo`로 배송형 데모 캠페인을 만들어 화면 확인 (인플루언서 DB · 배송형 칸반/시트 · 참여 상세의 게시물/지급 추가 · 콘텐츠 성과 · 정산 · 리포트). (커밋·푸시 완료 `be625c2`). 운영에는 Admin → 환율표에 쓰는 통화(USD·JPY·EUR 등) 환율을 먼저 넣습니다
- [ ] **운영 동작 확인:** 고객사·캠페인 생성 → 인플루언서 추가 → 단계 변경 → 시트 수정 → 고객사용 엑셀 다운로드. 확인 후 테스트 데이터를 캠페인 → 인플루언서 → 고객사 순서로 삭제
- [ ] **cron 확인:** Render `powerseed-sync-google-forms`에서 Trigger Run 후 성공 여부 확인
- [x] **Render 배포 브랜치를 `main`으로 전환 (2026-11-24 완료):** Blueprint 설정의 브랜치를 `main`으로 바꾸고, `powerseed-web`과 cron의 Settings에서 Branch가 `main`인지 확인. 이후 `main` 푸시마다 자동 배포됨
- [ ] **Gmail 연결:** 앱 비밀번호 발급 → Render `powerseed-web` Environment에 `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` 입력 → 실제 발송 1건 확인
- [ ] **구글 폼 연결:** 서비스 계정 JSON을 `powerseed-shared` Secret Files에 `google-service-account.json`으로 추가 → 테스트 폼 공유·연결 → 응답 반영과 미리 채우기 링크 확인
- [ ] **인스타 DM 연결:** Meta 앱 생성·검수 신청 → 토큰 입력 → 웹훅 `https://powerseed-web.onrender.com/hooks/instagram/` 등록 (구독 필드 `messages`, `message_echoes`) → 수신·발신 왕복 확인
- [ ] **Phase 6 릴스 평균:** 데이터 수집 방식 결정 후 착수 (수집기 보류와 연관). 고정 게시물 제외
- [ ] **(검토) TikTok·YouTube 핸들:** 지금 계정 칸은 인스타 규칙(영문 소문자·숫자·`.`·`_` 30자)으로 검사합니다. 유튜브 핸들의 `-` 등 다른 플랫폼 규칙이 필요하면 칸을 일반 핸들로 바꿔야 합니다

## 4. 보류·주의

- **수집기:** 기존 스크래퍼 코드를 받으면 `COLLECTOR_SCRAPER`로 연결합니다. 이때 수집이 웹 요청을 붙잡지 않도록 worker 백엔드를 함께 도입합니다. 스크래핑의 Meta 약관·계정 차단 위험도 먼저 점검합니다.
- **환율:** 원화 환산은 환율표 기준입니다. 환율표에 없는 통화로 지급 내역을 넣으면 원화 칸이 비고 화면에 경고가 뜹니다. 환율을 추가한 뒤 해당 지급 내역을 다시 저장하면 채워집니다.
- **HSTS:** 현재 1시간입니다. HTTPS가 안정되면 `DJANGO_SECURE_HSTS_SECONDS`를 늘립니다.
- **비밀값:** 토큰, 비밀번호, 서비스 계정 키는 git이나 채팅에 올리지 않고 Render Environment 또는 Secret Files에만 넣습니다.
- 배포 절차 상세는 [DEPLOY.md](DEPLOY.md), 전체 설계는 [ROADMAP.md](ROADMAP.md)를 봅니다.
