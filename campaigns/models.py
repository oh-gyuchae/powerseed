import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.choices import Currency
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


class CampaignKind(models.TextChoices):
    VISIT = "visit", "방문형"
    SHIPPING = "shipping", "배송형"


class Campaign(TimeStampedModel):
    Kind = CampaignKind

    class Status(models.TextChoices):
        PLANNING = "planning", "준비중"
        ACTIVE = "active", "진행중"
        DONE = "done", "완료"
        CANCELED = "canceled", "취소"

    client = models.ForeignKey(Client, verbose_name="고객사", on_delete=models.PROTECT, related_name="campaigns")
    name = models.CharField("캠페인명", max_length=200)
    kind = models.CharField(
        "캠페인 유형",
        max_length=10,
        choices=CampaignKind.choices,
        default=CampaignKind.VISIT,
        help_text="방문형: 매장 방문 후 업로드 / 배송형: 제품을 보내고 초안 검수 후 업로드 (해외 캠페인). "
        "인플루언서를 추가한 뒤에는 바꾸지 마세요 — 단계 목록이 달라집니다.",
    )
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

    def clean(self):
        # 유형을 바꾸면 단계 목록이 달라진다 — 새 유형에 없는 단계의 참여 건이 있으면 막는다.
        if self.pk:
            allowed = [s.value for s in stages_for(self.kind)]
            if self.participations.exclude(stage__in=allowed).exists():
                raise ValidationError(
                    {"kind": "이 유형에 없는 진행 단계의 인플루언서가 있어 유형을 바꿀 수 없습니다."}
                )

    @property
    def is_shipping(self):
        return self.kind == CampaignKind.SHIPPING

    @property
    def pipeline(self):
        return PIPELINES[self.kind]

    @property
    def stages(self):
        return stages_for(self.kind)

    @property
    def stage_choices(self):
        return [(s.value, s.label) for s in self.stages]


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
    # 배송형 전용
    REPLIED = "replied", "회신"
    CONTRACTED = "contracted", "계약"
    SHIPPED = "shipped", "제품 발송"
    RECEIVED = "received", "수령"
    DRAFT_REVIEW = "draft_review", "초안 검수"

    DECLINED = "declined", "거절"
    DROPPED = "dropped", "중도 이탈"
    NO_RESPONSE = "no_response", "무응답"


# 캠페인 유형별 진행 순서. EXIT_STAGES[유형]은 어느 진행 단계에서든 갈 수 있는 종료 단계.
# 같은 의미의 단계는 유형이 달라도 같은 값을 쓴다 (업로드 완료·지급 완료 등) — 집계를 합치기 위해.
PIPELINES = {
    CampaignKind.VISIT: [
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
    ],
    CampaignKind.SHIPPING: [
        Stage.CONTACT_TARGET,
        Stage.CONTACTED,
        Stage.REPLIED,
        Stage.NEGOTIATING,
        Stage.CONTRACTED,
        Stage.SHIPPED,
        Stage.RECEIVED,
        Stage.DRAFT_REVIEW,
        Stage.UPLOADED,
        Stage.PAID,
    ],
}
EXIT_STAGES = {
    CampaignKind.VISIT: [Stage.DECLINED, Stage.DROPPED],
    CampaignKind.SHIPPING: [Stage.DECLINED, Stage.NO_RESPONSE, Stage.DROPPED],
}
# 대시보드 퍼널 기준: 이 단계 이상(또는 거절)이면 '회신', 이 단계 이상이면 '계약'으로 센다.
REPLY_STAGE = {CampaignKind.VISIT: Stage.RESPONDED, CampaignKind.SHIPPING: Stage.REPLIED}
CONTRACT_STAGE = {CampaignKind.VISIT: Stage.CONFIRMED, CampaignKind.SHIPPING: Stage.CONTRACTED}

CLOSED_STAGES = {Stage.PAID, Stage.DECLINED, Stage.DROPPED, Stage.NO_RESPONSE}
DROPPED_OUT_STAGES = {Stage.DECLINED, Stage.DROPPED, Stage.NO_RESPONSE}  # 지급 완료를 뺀 종료 단계


def stages_for(kind):
    return PIPELINES[kind] + EXIT_STAGES[kind]


def _between(kind, start, end):
    pipeline = PIPELINES[kind]
    return pipeline[pipeline.index(start) : pipeline.index(end)]


# 참여가 확정(계약)됐고 아직 업로드 전인 단계 — 업로드 기한 경과 판단 기준
WAITING_UPLOAD_STAGES = {
    *_between(CampaignKind.VISIT, Stage.CONFIRMED, Stage.UPLOADED),
    *_between(CampaignKind.SHIPPING, Stage.CONTRACTED, Stage.UPLOADED),
}


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

    class CollabType(models.TextChoices):
        PAID = "paid", "유료"
        GIFTING = "gifting", "기프팅(무료 제공)"
        AFFILIATE = "affiliate", "제휴(어필리에이트)"

    fee_requested = models.PositiveIntegerField("희망 원고료(원)", null=True, blank=True)
    fee_amount = models.PositiveIntegerField("원고료", null=True, blank=True, help_text="확정 원고료 (계약 금액)")
    fee_currency = models.CharField("원고료 통화", max_length=3, choices=Currency.choices, default=Currency.KRW)
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

    # 배송형(해외) 진행 정보
    collab_type = models.CharField("협업 유형", max_length=10, choices=CollabType.choices, blank=True)
    deliverables = models.CharField("결과물", max_length=200, blank=True, help_text="예: 릴스 1 + 스토리 2")
    carrier = models.CharField("배송사", max_length=50, blank=True)
    tracking_number = models.CharField("송장번호", max_length=100, blank=True)
    shipped_at = models.DateField("발송일", null=True, blank=True)
    customs_issue = models.CharField("통관 이슈", max_length=300, blank=True)
    received_at = models.DateField("수령일", null=True, blank=True)
    draft_submitted_at = models.DateField("초안 제출일", null=True, blank=True)
    revision_count = models.PositiveSmallIntegerField("수정 횟수", default=0)
    usage_rights_until = models.DateField("2차 활용 종료일", null=True, blank=True, help_text="비우면 2차 활용 권리 없음")
    ad_usage_allowed = models.BooleanField("광고 집행 가능", default=False)
    ad_code = models.CharField("Spark Ads·화이트리스팅 코드", max_length=200, blank=True)
    disclosure_checked = models.BooleanField("광고 표기 확인", default=False, help_text="#ad, 유료 파트너십 라벨")
    last_contacted_at = models.DateField("마지막 연락일", null=True, blank=True, help_text="메시지를 보내면 자동 갱신")
    next_action = models.CharField("다음 할 일", max_length=200, blank=True)

    # 비용 (콘텐츠 성과·리포트 총비용에 포함, 원화)
    product_cost = models.PositiveIntegerField("제품 원가(원)", null=True, blank=True)
    shipping_cost = models.PositiveIntegerField("해외 배송비(원)", null=True, blank=True)

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

    @property
    def is_upload_overdue(self):
        """확정(계약) 후 업로드 기한이 지났는데 아직 안 올라온 건 (시트에서 빨갛게 표시)."""
        return bool(
            self.stage in WAITING_UPLOAD_STAGES
            and self.upload_due_at
            and self.upload_due_at < timezone.now()
            and not self.uploaded_at
        )

    @property
    def is_committed(self):
        """참여 확정(방문형) / 계약(배송형) 이후 진행 중이거나 완료된 건 — 예상 비용에 원고료를 넣는 기준."""
        pipeline = self.campaign.pipeline
        contract = CONTRACT_STAGE[self.campaign.kind]
        return self.stage in pipeline and pipeline.index(self.stage) >= pipeline.index(contract)


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
