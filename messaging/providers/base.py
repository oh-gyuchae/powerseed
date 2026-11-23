"""메시징 채널 공통 인터페이스. 새 채널 = 이 클래스를 상속한 Provider 1개 + providers/__init__.py 등록."""


class ProviderError(Exception):
    """발송 실패 — 메시지는 화면에 그대로 보여준다 (한국어)."""


class MessagingProvider:
    channel: str = ""
    label: str = ""
    supports_subject = False

    def is_configured(self) -> bool:
        raise NotImplementedError

    def recipient(self, participation) -> str:
        """받는 사람 표시용 (이메일 주소, @계정 등)."""
        raise NotImplementedError

    def unavailable_reason(self, participation) -> str | None:
        """지금 이 참여 건에 보낼 수 없는 이유. 보낼 수 있으면 None."""
        raise NotImplementedError

    def send(self, participation, *, subject: str, body: str) -> str:
        """발송하고 외부 메시지 ID를 돌려준다. 실패 시 ProviderError."""
        raise NotImplementedError
