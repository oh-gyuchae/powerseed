"""Google Forms API (v1) 읽기 전용 클라이언트 — 서비스 계정 인증.

폼은 서비스 계정 이메일(GOOGLE_SERVICE_ACCOUNT_FILE 안의 client_email)에 '편집자'로 공유되어 있어야 한다.
"""

import json
import re
from pathlib import Path

import httpx
from django.conf import settings

BASE_URL = "https://forms.googleapis.com/v1"
SCOPES = [
    "https://www.googleapis.com/auth/forms.body.readonly",
    "https://www.googleapis.com/auth/forms.responses.readonly",
]
# 편집 링크 https://docs.google.com/forms/d/<ID>/edit  (응답 링크 /forms/d/e/<ID>/viewform 과 다름)
_EDIT_URL_RE = re.compile(r"/forms/d/(?!e/)([A-Za-z0-9_-]{20,})")
_RESPONDER_URL_RE = re.compile(r"/forms/d/e/|forms\.gle/")


class GoogleFormsError(Exception):
    pass


def parse_form_id(value: str) -> str:
    value = (value or "").strip()
    if _RESPONDER_URL_RE.search(value):
        raise GoogleFormsError(
            "응답용 링크입니다. 구글 폼 편집 화면의 주소(…/forms/d/…/edit)를 붙여넣어 주세요."
        )
    match = _EDIT_URL_RE.search(value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", value):
        return value
    raise GoogleFormsError("구글 폼 편집 주소를 인식할 수 없습니다.")


def _service_account_path():
    raw = settings.GOOGLE_SERVICE_ACCOUNT_FILE
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else Path(settings.BASE_DIR) / path


def service_account_email():
    """폼 공유 안내용. 설정이 없거나 파일이 없으면 None."""
    path = _service_account_path()
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("client_email")
    except (OSError, ValueError):
        return None


class GoogleFormsClient:
    def __init__(self, credentials, http: httpx.Client | None = None):
        self._credentials = credentials
        self._http = http or httpx.Client(timeout=20)

    @classmethod
    def from_settings(cls):
        path = _service_account_path()
        if not path or not path.exists():
            raise GoogleFormsError(
                "구글 서비스 계정 파일이 설정되지 않았습니다. .env의 GOOGLE_SERVICE_ACCOUNT_FILE을 확인하세요."
            )
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)
        return cls(credentials)

    def _token(self):
        if not self._credentials.valid:
            from google.auth.transport.requests import Request

            try:
                self._credentials.refresh(Request())
            except Exception as e:  # google.auth.exceptions.* — 네트워크/키 오류
                raise GoogleFormsError(f"구글 인증에 실패했습니다: {e}") from e
        return self._credentials.token

    def _get(self, path, params=None):
        try:
            res = self._http.get(
                f"{BASE_URL}{path}", params=params, headers={"Authorization": f"Bearer {self._token()}"}
            )
        except httpx.HTTPError as e:
            raise GoogleFormsError(f"구글 폼 API 연결 실패: {e}") from e
        if res.status_code in (403, 404):
            email = service_account_email() or "서비스 계정"
            raise GoogleFormsError(
                f"폼에 접근할 수 없습니다. 구글 폼의 공유 설정에서 {email} 을(를) 편집자로 추가했는지 확인하세요."
            )
        if res.status_code >= 400:
            raise GoogleFormsError(f"구글 폼 API 오류 ({res.status_code}): {res.text[:300]}")
        return res.json()

    def get_form(self, form_id):
        return self._get(f"/forms/{form_id}")

    def list_responses(self, form_id):
        responses, page_token = [], None
        while True:
            params = {"pageSize": 5000}
            if page_token:
                params["pageToken"] = page_token
            data = self._get(f"/forms/{form_id}/responses", params)
            responses.extend(data.get("responses", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                return responses
