import uuid

from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class Client(TimeStampedModel):
    name = models.CharField("고객사명", max_length=100, unique=True)
    contact = models.CharField("담당자 연락처", max_length=200, blank=True)
    notes = models.TextField("비고", blank=True)

    class Meta:
        verbose_name = "고객사"
        verbose_name_plural = "고객사"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Campaign(TimeStampedModel):
    class Status(models.TextChoices):
        PLANNING = "planning", "준비중"
        ACTIVE = "active", "진행중"
        DONE = "done", "완료"
        CANCELED = "canceled", "취소"

    client = models.ForeignKey(Client, verbose_name="고객사", on_delete=models.PROTECT, related_name="campaigns")
    name = models.CharField("캠페인명", max_length=200)
    status = models.CharField("상태", max_length=10, choices=Status.choices, default=Status.PLANNING)
    guideline = models.TextField("가이드라인", blank=True, help_text="원고 가이드 본문 또는 링크")
    visit_location = models.CharField("방문 장소", max_length=300, blank=True)
    start_date = models.DateField("시작일", null=True, blank=True)
    end_date = models.DateField("종료일", null=True, blank=True)
    budget = models.PositiveIntegerField("예산(원)", null=True, blank=True)
    default_fee = models.PositiveIntegerField("기본 원고료(원)", null=True, blank=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="책임자",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_campaigns",
    )

    class Meta:
        verbose_name = "캠페인"
        verbose_name_plural = "캠페인"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.client}] {self.name}"


class Stage(models.TextChoices):
    CONTACT_TARGET = "contact_target", "컨택 대상"
    CONTACTED = "contacted", "컨택 완료"
    SURVEY_SENT = "survey_sent", "설문 발송"
    RESPONDED = "responded", "설문 응답"
    NEGOTIATING = "negotiating", "원고료 협상"
    CONFIRMED = "confirmed", "참여 확정"
    VISIT_SCHEDULED = "visit_scheduled", "방문 예정"
    VISITED = "visited", "방문 완료"
    UPLOADED = "uploaded", "업로드 완료"
    PAYOUT_PENDING = "payout_pending", "지급 대기"
    PAID = "paid", "지급 완료"
    DECLINED = "declined", "거절"
    DROPPED = "dropped", "중도 이탈"


# Linear pipeline order; DECLINED / DROPPED can be reached from any open stage.
PIPELINE = [
    Stage.CONTACT_TARGET,
    Stage.CONTACTED,
    Stage.SURVEY_SENT,
    Stage.RESPONDED,
    Stage.NEGOTIATING,
    Stage.CONFIRMED,
    Stage.VISIT_SCHEDULED,
    Stage.VISITED,
    Stage.UPLOADED,
    Stage.PAYOUT_PENDING,
    Stage.PAID,
]
CLOSED_STAGES = {Stage.PAID, Stage.DECLINED, Stage.DROPPED}


class Participation(TimeStampedModel):
    """캠페인 × 인플루언서. 파이프라인 1건 = 캠페인 시트 1행."""

    class ParticipationStatus(models.TextChoices):
        NO_RESPONSE = "no_response", "미응답"
        YES = "yes", "참여"
        NO = "no", "불참"
        CONSIDERING = "considering", "검토중"

    class PayoutMethod(models.TextChoices):
        BANK_TRANSFER = "bank_transfer", "계좌이체"
        TAX_INVOICE = "tax_invoice", "세금계산서(사업자)"
        PAYPAL = "paypal", "페이팔"
        PRODUCT_ONLY = "product_only", "제품 제공(무료)"
        OTHER = "other", "기타"

    class PayoutStatus(models.TextChoices):
        UNPAID = "unpaid", "미지급"
        PENDING = "pending", "지급 대기"
        PAID = "paid", "지급 완료"

    campaign = models.ForeignKey(
        Campaign, verbose_name="캠페인", on_delete=models.CASCADE, related_name="participations"
    )
    influencer = models.ForeignKey(
        "influencers.Influencer",
        verbose_name="인플루언서",
        on_delete=models.PROTECT,
        related_name="participations",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="담당자",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_participations",
    )

    stage = models.CharField(
        "진행 단계", max_length=20, choices=Stage.choices, default=Stage.CONTACT_TARGET, db_index=True
    )
    participation_status = models.CharField(
        "참여 의사",
        max_length=15,
        choices=ParticipationStatus.choices,
        default=ParticipationStatus.NO_RESPONSE,
    )
    available_visit_dates = models.JSONField(
        "방문 가능일", default=list, blank=True, help_text="YYYY-MM-DD 문자열 리스트"
    )
    confirmed_visit_at = models.DateTimeField("확정 방문 일시", null=True, blank=True)

    fee_requested = models.PositiveIntegerField("희망 원고료(원)", null=True, blank=True)
    fee_amount = models.PositiveIntegerField("원고료(원)", null=True, blank=True, help_text="확정 원고료")
    payout_method = models.CharField("송금 수단", max_length=15, choices=PayoutMethod.choices, blank=True)
    payout_status = models.CharField(
        "지급 상태", max_length=10, choices=PayoutStatus.choices, default=PayoutStatus.UNPAID
    )
    paid_at = models.DateTimeField("지급일", null=True, blank=True)

    upload_due_at = models.DateTimeField("업로드 기한", null=True, blank=True)
    upload_url = models.URLField("업로드 URL", blank=True)
    uploaded_at = models.DateTimeField("업로드 일시", null=True, blank=True)

    survey_token = models.UUIDField("설문 토큰", default=uuid.uuid4, unique=True, editable=False)
    survey_submitted_at = models.DateTimeField("설문 제출일", null=True, blank=True)
    form_answers = models.JSONField(
        "설문 추가 답변", default=dict, blank=True, help_text="구글 폼 '추가 답변' 문항: {질문 ID: 답변}"
    )

    notes = models.TextField("비고", blank=True)
    special_notes = models.TextField("특이사항", blank=True)

    class Meta:
        verbose_name = "참여 인플루언서"
        verbose_name_plural = "참여 인플루언서"
        ordering = ["campaign", "-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["campaign", "influencer"], name="uniq_campaign_influencer"),
        ]

    def __str__(self):
        return f"{self.campaign.name} / {self.influencer}"

    @property
    def is_closed(self):
        return self.stage in CLOSED_STAGES


class StatusLog(models.Model):
    """단계 변경 이력 — 중간관리자 진행 파악용."""

    participation = models.ForeignKey(Participation, on_delete=models.CASCADE, related_name="status_logs")
    from_stage = models.CharField("이전 단계", max_length=20, choices=Stage.choices, blank=True)
    to_stage = models.CharField("변경 단계", max_length=20, choices=Stage.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="변경자", null=True, blank=True, on_delete=models.SET_NULL
    )
    memo = models.CharField("메모", max_length=300, blank=True)
    created_at = models.DateTimeField("변경 일시", auto_now_add=True)

    class Meta:
        verbose_name = "단계 변경 이력"
        verbose_name_plural = "단계 변경 이력"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.participation_id}: {self.from_stage or '-'} → {self.to_stage}"
