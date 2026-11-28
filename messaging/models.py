from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class Channel(models.TextChoices):
    INSTAGRAM = "instagram", "인스타그램 DM"
    EMAIL = "email", "이메일(Gmail)"


class MessageTemplate(TimeStampedModel):
    """발송 문구 템플릿. 변수: {{이름}} {{계정}} {{캠페인}} {{방문장소}} {{설문링크}}"""

    name = models.CharField("템플릿 이름", max_length=100)
    channel = models.CharField("채널", max_length=20, choices=Channel.choices, blank=True, help_text="비우면 모든 채널")
    subject = models.CharField("메일 제목", max_length=200, blank=True, help_text="이메일에서만 사용")
    body = models.TextField("본문")

    class Meta:
        verbose_name = "메시지 템플릿"
        verbose_name_plural = "메시지 템플릿"
        ordering = ["name"]

    def __str__(self):
        return self.name


class InstagramThread(TimeStampedModel):
    """인스타 DM 대화 상대 1명. Meta 웹훅으로 들어온 IGSID를 인플루언서와 연결한다."""

    igsid = models.CharField("인스타 사용자 ID(IGSID)", max_length=64, unique=True)
    username = models.CharField("인스타 계정", max_length=100, blank=True)
    influencer = models.ForeignKey(
        "influencers.Influencer",
        verbose_name="인플루언서",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="instagram_threads",
    )
    last_inbound_at = models.DateTimeField(
        "상대 마지막 메시지", null=True, blank=True, help_text="이 시각부터 24시간 동안만 API로 답장 가능(Meta 정책)"
    )

    class Meta:
        verbose_name = "인스타 DM 대화"
        verbose_name_plural = "인스타 DM 대화"
        ordering = ["-last_inbound_at"]

    def __str__(self):
        return f"@{self.username}" if self.username else self.igsid


class Message(models.Model):
    class Direction(models.TextChoices):
        OUT = "out", "보냄"
        IN = "in", "받음"

    class Status(models.TextChoices):
        SENT = "sent", "발송 완료"
        FAILED = "failed", "발송 실패"
        RECEIVED = "received", "수신"

    channel = models.CharField("채널", max_length=20, choices=Channel.choices)
    direction = models.CharField("방향", max_length=3, choices=Direction.choices)
    status = models.CharField("상태", max_length=10, choices=Status.choices)
    influencer = models.ForeignKey(
        "influencers.Influencer",
        verbose_name="인플루언서",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="messages",
    )
    participation = models.ForeignKey(
        "campaigns.Participation",
        verbose_name="참여 건",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="messages",
    )
    thread = models.ForeignKey(
        InstagramThread, verbose_name="인스타 대화", null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    recipient = models.CharField("받는 사람", max_length=254, blank=True)
    subject = models.CharField("제목", max_length=200, blank=True)
    body = models.TextField("내용", blank=True)
    error = models.TextField("오류", blank=True)
    external_id = models.CharField("외부 메시지 ID", max_length=200, blank=True, db_index=True)
    manual = models.BooleanField("직접 발송", default=False, help_text="인스타 앱 등에서 직접 보내고 기록만 남긴 메시지")
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="보낸 직원", null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField("일시", auto_now_add=True)

    class Meta:
        verbose_name = "메시지"
        verbose_name_plural = "메시지"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_channel_display()}/{self.get_direction_display()}] {self.recipient}"
