# PowerSeed

광고대행사용 인플루언서 시딩 CRM.
흐름: 해시태그 수집 → 컨택 → 설문 → 구글 시트 자동 기입 → 진행 트래킹 → 원고료 지급

## 로컬 실행

```bash
python -m venv .venv
.venv/Scripts/activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # 값 채우기
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver      # http://127.0.0.1:8000/admin/
python manage.py test
```

## 앱 구성

| 앱 | 역할 | 상태 |
|---|---|---|
| `core` | 공용 베이스 모델(TimeStampedModel) | ✅ |
| `influencers` | 인플루언서 계정 마스터 (계정 이름·플랫폼·인스타 계정·URL·팔로워·한 달 릴스 평균·비고·특이사항) | ✅ |
| `campaigns` | 고객사·캠페인·참여 파이프라인(Participation)·단계 변경 이력(StatusLog) | ✅ |
| `surveys` | 토큰 기반 공개 설문 폼 | Phase 3 |
| `sheets` | DB → 구글 시트 단방향 upsert | Phase 3 |
| `collector` | 해시태그 수집기 연동 | Phase 4 |
| `messaging` | 채널톡 연동 (Provider 패턴으로 인스타/Gmail/카카오/LINE 확장) | Phase 5 |
| `metrics` | 한 달 릴스 평균 = 최근 30일 릴스 평균 조회수 자동 산출 | Phase 6 |

## 진행 단계 (Participation.stage)

컨택 대상 → 컨택 완료 → 설문 발송 → 설문 응답 → 원고료 협상 → 참여 확정 → 방문 예정 → 방문 완료 → 업로드 완료 → 지급 대기 → 지급 완료
(어느 단계에서든 거절 / 중도 이탈 가능)

단계 변경은 반드시 `campaigns.services.change_stage()`를 거칩니다. 이력이 기록되고 지급 상태·업로드 일시 같은 연관 필드가 자동으로 맞춰집니다.

## 로드맵

- [x] Phase 0 — 기반 정리 (.gitignore, 환경변수 설정, ko-kr/Asia/Seoul)
- [x] Phase 1 — 핵심 모델 + Admin + 단계 전이 서비스
- [ ] Phase 2 — 운영 화면 (캠페인 칸반, 중간관리자 대시보드)
- [ ] Phase 3 — 설문 + 구글 시트 동기화
- [ ] Phase 4 — 해시태그 수집기 편입
- [ ] Phase 5 — 채널톡 연동
- [ ] Phase 6 — 릴스 평균 자동 산출
- [ ] Phase 7 — 배포
