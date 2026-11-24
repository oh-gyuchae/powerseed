"""시트 ④ 정산 — 지급 1건 = Payment 1행. 환율표(설정 탭)는 ExchangeRate.

원화 환산액은 저장할 때 계산해 둔다 (적용 환율을 비워 두면 환율표에서 지급일 기준으로 채움).
통화가 섞여도 국가·캠페인 간 비교는 원화 환산액으로 한다.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.utils import timezone

from core.choices import Currency
from core.models import TimeStampedModel


class ExchangeRate(TimeStampedModel):
    currency = models.CharField("통화", max_length=3, choices=Currency.choices)
    rate = models.DecimalField(
        "환율(원)", max_digits=14, decimal_places=4, help_text="1 단위당 원화. 예: USD 1,380 / JPY 9.2"
    )
    effective_date = models.DateField("적용 시작일", default=timezone.localdate)
    notes = models.CharField("메모", max_length=200, blank=True)

    class Meta:
        verbose_name = "환율"
        verbose_name_plural = "환율표"
        ordering = ["currency", "-effective_date"]
        constraints = [
            models.UniqueConstraint(fields=["currency", "effective_date"], name="uniq_rate_per_day"),
            models.CheckConstraint(condition=models.Q(rate__gt=0), name="rate_positive"),
        ]

    def __str__(self):
        return f"{self.currency} {self.rate}원 ({self.effective_date})"


def rate_for(currency, on=None) -> Decimal | None:
    """`on` 날짜(기본 오늘)에 적용되는 원화 환율. KRW는 1, 등록된 환율이 없으면 None."""
    if currency == Currency.KRW:
        return Decimal(1)
    on = on or timezone.localdate()
    found = (
        ExchangeRate.objects.filter(currency=currency, effective_date__lte=on)
        .order_by("-effective_date")
        .values_list("rate", flat=True)
        .first()
    )
    return found


def to_krw(amount, rate) -> int | None:
    if amount is None or rate is None:
        return None
    return int((Decimal(amount) * Decimal(rate)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


class Payment(TimeStampedModel):
    class Installment(models.TextChoices):
        DEPOSIT = "deposit", "선금"
        BALANCE = "balance", "잔금"
        FULL = "full", "전액"

    class Method(models.TextChoices):
        PAYPAL = "paypal", "PayPal"
        WISE = "wise", "Wise"
        BANK_TRANSFER = "bank_transfer", "계좌이체"
        OTHER = "other", "기타"

    class TaxDocument(models.TextChoices):
        NONE = "none", "불필요"
        W8BEN = "w8ben", "W-8BEN"
        W9 = "w9", "W-9"
        OTHER = "other", "기타"

    participation = models.ForeignKey(
        "campaigns.Participation", verbose_name="참여 인플루언서", on_delete=models.CASCADE, related_name="payments"
    )
    installment = models.CharField("구분", max_length=10, choices=Installment.choices, default=Installment.FULL)
    amount = models.DecimalField("금액", max_digits=12, decimal_places=2)
    currency = models.CharField("통화", max_length=3, choices=Currency.choices, default=Currency.USD)
    fx_rate = models.DecimalField(
        "적용 환율",
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="비우면 환율표에서 지급일(없으면 오늘) 기준 환율을 채웁니다.",
    )
    amount_krw = models.PositiveIntegerField("원화 환산액", null=True, blank=True, editable=False)
    method = models.CharField("지급 방법", max_length=15, choices=Method.choices, blank=True)
    fee = models.DecimalField("수수료", max_digits=12, decimal_places=2, null=True, blank=True, help_text="지급 통화 기준")
    fee_krw = models.PositiveIntegerField("수수료(원)", null=True, blank=True, editable=False)
    tax_document = models.CharField("세금 서류", max_length=10, choices=TaxDocument.choices, default=TaxDocument.NONE)
    tax_document_received = models.BooleanField("세금 서류 수령", default=False)
    invoice_received = models.BooleanField("인보이스 수령", default=False)
    paid_at = models.DateField("지급일", null=True, blank=True, help_text="비워 두면 지급 예정")
    notes = models.CharField("메모", max_length=300, blank=True)

    class Meta:
        verbose_name = "지급 내역"
        verbose_name_plural = "지급 내역"
        ordering = ["-paid_at", "-created_at"]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gte=0), name="payment_amount_nonneg")]

    def __str__(self):
        return f"{self.participation} / {self.get_installment_display()} {self.amount} {self.currency}"

    @property
    def is_paid(self):
        return self.paid_at is not None

    @property
    def status_label(self):
        return f"{self.get_installment_display()} {'지급 완료' if self.is_paid else '지급 예정'}"

    @property
    def cost_krw(self):
        """총비용에 들어가는 원화 금액 (금액 + 수수료). 환율이 없으면 None."""
        if self.amount_krw is None:
            return None
        return self.amount_krw + (self.fee_krw or 0)

    def save(self, *args, **kwargs):
        if self.fx_rate is None:
            self.fx_rate = rate_for(self.currency, self.paid_at)
        self.amount_krw = to_krw(self.amount, self.fx_rate)
        self.fee_krw = to_krw(self.fee, self.fx_rate) if self.fee is not None else None
        super().save(*args, **kwargs)
