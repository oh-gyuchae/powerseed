"""Gmail 발송 (SMTP + 앱 비밀번호). 발송만 하고 답장은 Gmail에서 직접 확인한다."""

import smtplib
from email.utils import formataddr, make_msgid

from django.conf import settings
from django.core.mail import EmailMessage

from ..models import Channel
from .base import MessagingProvider, ProviderError

MAILER_ALIAS = "gmail"  # settings.MAILERS["gmail"]


class GmailProvider(MessagingProvider):
    channel = Channel.EMAIL
    label = "이메일(Gmail)"
    supports_subject = True

    def is_configured(self):
        return bool(settings.GMAIL_ADDRESS and settings.GMAIL_APP_PASSWORD)

    def recipient(self, participation):
        return participation.influencer.email

    def unavailable_reason(self, participation):
        if not self.is_configured():
            return "Gmail 발송 설정이 없습니다 (.env의 GMAIL_ADDRESS / GMAIL_APP_PASSWORD)."
        if not participation.influencer.email:
            return "인플루언서 이메일이 없습니다. 계정 정보에 이메일을 입력하거나 설문으로 받아 주세요."
        return None

    def send(self, participation, *, subject, body):
        if not subject.strip():
            raise ProviderError("메일 제목을 입력하세요.")
        domain = settings.GMAIL_ADDRESS.rsplit("@", 1)[-1]
        message_id = make_msgid(domain=domain)
        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=formataddr((settings.GMAIL_FROM_NAME, settings.GMAIL_ADDRESS)),
            to=[participation.influencer.email],
            headers={"Message-ID": message_id},
        )
        try:
            email.send(using=MAILER_ALIAS)
        except smtplib.SMTPAuthenticationError as e:
            raise ProviderError("Gmail 로그인 실패: 앱 비밀번호를 확인하세요 (2단계 인증 필요).") from e
        except (smtplib.SMTPException, OSError) as e:
            raise ProviderError(f"메일 발송 실패: {e}") from e
        return message_id
