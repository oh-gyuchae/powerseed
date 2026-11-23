# 배포 (Render + Docker + PostgreSQL)

구성은 `render.yaml`에 있습니다: 웹 서비스, PostgreSQL, 10분마다 구글 폼을 동기화하는 cron. 세 서비스 모두 유료 플랜입니다. 금액은 Render 요금 화면에서 확인하세요.

## 처음 배포
1. 이 코드를 GitHub `feat/sheet-forms-messaging` 브랜치에 올립니다. 운영 확인 후 `main`에 병합하고 `render.yaml`의 `branch`와 Render 배포 브랜치를 `main`으로 바꿉니다.
2. Render → **New → Blueprint** → 이 저장소와 위 브랜치를 선택합니다.
3. 입력 칸이 뜨면 Gmail·Meta 값을 넣습니다. 아직 없으면 비워 두고 나중에 웹 서비스 Environment에서 넣어도 됩니다.
4. 구글 폼을 쓰려면 Environment Group `powerseed-shared`의 **Secret Files**에 `google-service-account.json`을 추가합니다. 웹과 cron이 함께 씁니다.
5. 배포가 끝나면 웹 서비스 **Shell**에서 관리자 계정을 만듭니다.
   ```bash
   python manage.py createsuperuser
   ```
   운영에서는 `seed_demo`(admin/admin)가 실행되지 않습니다.

## 배포 후 확인
- `https://<서비스 주소>/healthz` 가 `ok`
- 로그인, 캠페인 생성, 시트 수정, 고객사용 엑셀 다운로드
- Meta 웹훅 콜백을 `https://<서비스 주소>/hooks/instagram/` 로 등록 (구독 필드 `messages`, `message_echoes`)
- cron `powerseed-sync-google-forms` 실행 로그

## 참고
- 마이그레이션은 배포 직전에 자동 실행됩니다.
- HSTS는 1시간으로 시작합니다. HTTPS가 안정적이면 `DJANGO_SECURE_HSTS_SECONDS`를 늘립니다.
- 자체 도메인을 연결하면 `DJANGO_ALLOWED_HOSTS`와 `SITE_BASE_URL`에 도메인을 넣습니다.
- 해시태그 수집기는 보류 상태입니다. 연결할 때 수집이 웹 요청을 붙잡지 않도록 worker 백엔드를 함께 도입합니다.
