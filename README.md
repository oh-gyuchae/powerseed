# PowerSeed

광고대행사용 인플루언서 시딩 CRM.
흐름: 해시태그 수집 → 컨택 → 설문 → 구글 시트 자동 기입 → 진행 트래킹 → 원고료 지급

전체 설계와 단계별 계획은 [docs/ROADMAP.md](docs/ROADMAP.md)를 참고하세요.

## 로컬 실행 (새 기기에서 처음 받을 때)

```bash
git clone git@github.com:oh-gyuchae/powerseed.git
cd powerseed
git checkout feat/first-push

python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # 로컬은 기본값 그대로 사용 가능

python manage.py migrate
python manage.py seed_demo      # 데모 데이터 + 관리자 계정 admin / admin
python manage.py runserver
```

- 운영 화면: http://127.0.0.1:8000/ (admin / admin 로그인)
- 데이터 관리(Django Admin): http://127.0.0.1:8000/admin/
- 테스트: `python manage.py test`

> `db.sqlite3`와 `.env`는 git에 올리지 않습니다. 기기마다 `migrate` + `seed_demo`로 새로 만듭니다.

## 화면

| URL | 내용 |
|---|---|
| `/` | 중간관리자 대시보드: 캠페인별 단계 집계, 주의 목록(방문일 경과 · 업로드 기한 경과 · 설문 3일+ 미응답 · 지급 대기), 내 담당 필터 |
| `/campaigns/<id>/` | 캠페인 칸반: 단계별 카드, 카드에서 바로 단계 변경(HTMX), 담당자 필터, 인스타 계정 일괄 추가 |
| `/participations/<id>/` | 참여 상세: 원고료·방문일·송금 수단·업로드 URL·비고 편집, 단계 변경/재오픈, 변경 이력 |

## 앱 구성

| 앱 | 역할 | 상태 |
|---|---|---|
| `core` | 공용 베이스 모델(TimeStampedModel) | ✅ |
| `influencers` | 인플루언서 계정 마스터 (계정 이름·플랫폼·인스타 계정·URL·팔로워·한 달 릴스 평균·비고·특이사항) | ✅ |
| `campaigns` | 고객사·캠페인·참여 파이프라인(Participation)·단계 이력(StatusLog), 대시보드/칸반 화면 | ✅ |
| `surveys` | 토큰 기반 공개 설문 폼 | Phase 3 |
| `sheets` | DB → 구글 시트 단방향 upsert | Phase 3 |
| `collector` | 해시태그 수집기(Python 스크래퍼) 연동 | Phase 4 |
| `messaging` | 채널톡 연동 (Provider 패턴으로 인스타/Gmail/카카오/LINE 확장) | Phase 5 |
| `metrics` | 한 달 릴스 평균 = 최근 30일 릴스 평균 조회수 자동 산출 | Phase 6 |

## 진행 단계 (Participation.stage)

컨택 대상 → 컨택 완료 → 설문 발송 → 설문 응답 → 원고료 협상 → 참여 확정 → 방문 예정 → 방문 완료 → 업로드 완료 → 지급 대기 → 지급 완료
(어느 단계에서든 거절 / 중도 이탈 가능)

단계 변경은 반드시 `campaigns.services.change_stage()`를 거칩니다. 이력이 기록되고 지급 상태·업로드 일시 같은 연관 필드가 자동으로 맞춰집니다.

## 로드맵

- [x] Phase 0 — 기반 정리 (.gitignore, 환경변수 설정, ko-kr/Asia/Seoul)
- [x] Phase 1 — 핵심 모델 + Admin + 단계 전이 서비스
- [x] Phase 2 — 운영 화면 (캠페인 칸반, 중간관리자 대시보드, 참여 상세)
- [ ] Phase 3 — 설문 + 구글 시트 동기화 ← **다음 작업**
- [ ] Phase 4 — 해시태그 수집기 편입
- [ ] Phase 5 — 채널톡 연동
- [ ] Phase 6 — 릴스 평균 자동 산출
- [ ] Phase 7 — 배포

### 다음 작업에 필요한 것
- Phase 3: 구글 서비스 계정 JSON(`secrets/` 폴더에 두고 `.env`의 `GOOGLE_SERVICE_ACCOUNT_FILE` 지정, git 제외됨) + 대상 스프레드시트를 서비스 계정 이메일에 편집자로 공유
- Phase 4: 기존 해시태그 수집기 코드
- Phase 5: 채널톡 Access Key/Secret, 웹훅 설정 권한
