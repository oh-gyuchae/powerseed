"""인스타그램 DM — Meta Instagram API(Instagram 로그인 방식) 직접 연동.

Meta 정책: 비즈니스 계정이 먼저 DM을 보낼 수 없고, 상대가 보낸 마지막 메시지로부터 24시간 이내에만 API로 답장할 수 있다.
그래서 첫 콜드 DM은 인스타 앱에서 직접 보내고, 상대가 답장하면(웹훅 수신) 그때부터 플랫폼에서 발송한다.
"""

import hashlib
import hmac
from datetime import timedelta

import httpx
from django.conf import settings
from django.utils import timezone

from ..models import Channel, InstagramThread
from .base import MessagingProvider, ProviderError

REPLY_WINDOW = timedelta(hours=24)
MAX_TEXT_LENGTH = 1000


def _api_url(path):
    return f"{settings.INSTAGRAM_GRAPH_BASE_URL}/{settings.META_GRAPH_API_VERSION}/{path}"


class InstagramProvider(MessagingProvider):
    channel = Channel.INSTAGRAM
    label = "인스타그램 DM"

    def __init__(self, http: httpx.Client | None = None):
        self._http = http

    @property
    def http(self):
        if self._http is None:
            self._http = httpx.Client(timeout=20)
        return self._http

    def is_configured(self):
        return bool(settings.INSTAGRAM_ACCESS_TOKEN)

    # ---------------------------------------------------------------- 발송

    def thread_for(self, participation):
        return (
            InstagramThread.objects.filter(influencer=participation.influencer)
            .order_by("-last_inbound_at")
            .first()
        )

    def recipient(self, participation):
        return f"@{participation.influencer.instagram_handle}"

    def unavailable_reason(self, participation):
        if not self.is_configured():
            return "인스타그램 API 설정이 없습니다 (.env의 INSTAGRAM_ACCESS_TOKEN)."
        thread = self.thread_for(participation)
        if thread is None or thread.last_inbound_at is None:
            return "아직 이 계정에서 받은 DM이 없습니다. 첫 DM은 인스타 앱에서 직접 보내 주세요 (Meta 정책)."
        if timezone.now() - thread.last_inbound_at > REPLY_WINDOW:
            last = timezone.localtime(thread.last_inbound_at).strftime("%m/%d %H:%M")
            return f"상대의 마지막 메시지({last})로부터 24시간이 지나 API로 보낼 수 없습니다. 인스타 앱에서 직접 보내 주세요."
        return None

    def send(self, participation, *, subject, body):
        if len(body) > MAX_TEXT_LENGTH:
            raise ProviderError(f"인스타 DM은 {MAX_TEXT_LENGTH}자까지 보낼 수 있습니다 (현재 {len(body)}자).")
        thread = self.thread_for(participation)
        data = self._request(
            "post",
            f"{settings.INSTAGRAM_ACCOUNT_ID}/messages",
            json={"recipient": {"id": thread.igsid}, "message": {"text": body}},
        )
        return data.get("message_id", "")

    def fetch_username(self, igsid):
        """웹훅으로 받은 IGSID -> 인스타 계정명. 실패하면 ''."""
        if not self.is_configured():
            return ""
        try:
            return self._request("get", igsid, params={"fields": "username"}).get("username", "")
        except ProviderError:
            return ""

    def _request(self, method, path, **kwargs):
        headers = {"Authorization": f"Bearer {settings.INSTAGRAM_ACCESS_TOKEN}"}
        try:
            res = self.http.request(method, _api_url(path), headers=headers, **kwargs)
        except httpx.HTTPError as e:
            raise ProviderError(f"인스타그램 API 연결 실패: {e}") from e
        try:
            data = res.json()
        except ValueError:
            data = {}
        if res.status_code >= 400:
            detail = (data.get("error") or {}).get("message") or res.text[:200]
            raise ProviderError(f"인스타그램 API 오류 ({res.status_code}): {detail}")
        return data

    # ---------------------------------------------------------------- 웹훅

    @staticmethod
    def verify_challenge(params):
        """웹훅 등록 시 Meta가 보내는 GET 확인 요청. 맞으면 challenge 문자열, 아니면 None."""
        token = settings.META_WEBHOOK_VERIFY_TOKEN
        if token and params.get("hub.mode") == "subscribe" and hmac.compare_digest(
            params.get("hub.verify_token", ""), token
        ):
            return params.get("hub.challenge", "")
        return None

    @staticmethod
    def verify_signature(body: bytes, header: str) -> bool:
        secret = settings.META_APP_SECRET
        if not secret or not header.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, header.removeprefix("sha256="))

    @staticmethod
    def parse_events(payload):
        """웹훅 본문 -> [{igsid, mid, text, timestamp(ms), is_echo}] (텍스트 메시지만)."""
        events = []
        if payload.get("object") != "instagram":
            return events
        for entry in payload.get("entry", []):
            for item in entry.get("messaging", []):
                message = item.get("message") or {}
                if not message.get("mid") or message.get("is_deleted"):
                    continue
                is_echo = bool(message.get("is_echo"))
                # 에코(우리 계정이 보낸 메시지)는 받는 사람이 대화 상대
                other = item.get("recipient" if is_echo else "sender", {}).get("id")
                if not other:
                    continue
                events.append(
                    {
                        "igsid": other,
                        "mid": message["mid"],
                        "text": message.get("text", ""),
                        "timestamp": item.get("timestamp"),
                        "is_echo": is_echo,
                    }
                )
        return events
