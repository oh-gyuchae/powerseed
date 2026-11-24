from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from campaigns import services
from campaigns.models import Campaign, CampaignKind, Client, Stage
from influencers.models import Influencer
from payments.models import ExchangeRate, Payment, rate_for, to_krw
from payments.services import CostBook


class RateTests(TestCase):
    def test_rate_for_uses_latest_effective_rate(self):
        ExchangeRate.objects.create(currency="USD", rate=Decimal("1300"), effective_date=date(2026, 1, 1))
        ExchangeRate.objects.create(currency="USD", rate=Decimal("1400"), effective_date=date(2026, 6, 1))
        self.assertEqual(rate_for("USD", date(2026, 3, 1)), Decimal("1300"))
        self.assertEqual(rate_for("USD", date(2026, 7, 1)), Decimal("1400"))
        self.assertIsNone(rate_for("USD", date(2025, 12, 31)))
        self.assertEqual(rate_for("KRW"), 1)
        self.assertIsNone(rate_for("JPY"))

    def test_to_krw_rounds_half_up(self):
        self.assertEqual(to_krw(Decimal("10.05"), Decimal("1380.5")), 13874)
        self.assertIsNone(to_krw(None, 1))


class PaymentBase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ops", password="pw-12345")
        self.client.force_login(self.user)
        self.campaign = Campaign.objects.create(
            client=Client.objects.create(name="고객사A"), name="해외", kind=CampaignKind.SHIPPING
        )
        self.inf = Influencer.objects.create(instagram_handle="us_glow", country="US")
        self.p, _ = services.add_to_campaign(self.inf, self.campaign)
        ExchangeRate.objects.create(currency="USD", rate=Decimal("1380"), effective_date=date(2026, 1, 1))


class PaymentTests(PaymentBase):
    def test_save_fills_rate_and_krw(self):
        pay = Payment.objects.create(
            participation=self.p, amount=Decimal("500"), currency="USD", fee=Decimal("10"), paid_at=date(2026, 2, 1)
        )
        self.assertEqual((pay.fx_rate, pay.amount_krw, pay.fee_krw, pay.cost_krw), (Decimal("1380"), 690000, 13800, 703800))
        self.assertEqual(pay.status_label, "전액 지급 완료")

    def test_explicit_rate_is_kept_and_missing_rate_leaves_krw_empty(self):
        pay = Payment.objects.create(participation=self.p, amount=Decimal("100"), currency="USD", fx_rate=Decimal("1500"))
        self.assertEqual(pay.amount_krw, 150000)
        jpy = Payment.objects.create(participation=self.p, amount=Decimal("1000"), currency="JPY")
        self.assertIsNone(jpy.amount_krw)
        self.assertIsNone(jpy.cost_krw)


class CostBookTests(PaymentBase):
    def test_payments_plus_product_and_shipping(self):
        Payment.objects.create(participation=self.p, amount=Decimal("500"), currency="USD", paid_at=date(2026, 2, 1))
        self.p.product_cost, self.p.shipping_cost = 30000, 40000
        self.p.save()
        self.assertEqual(CostBook().participation_cost(self.p), 690000 + 70000)

    def test_fee_estimate_only_after_contract(self):
        self.p.fee_amount, self.p.fee_currency = 500, "USD"
        self.p.save()
        self.assertEqual(CostBook().participation_cost(self.p), 0)  # 컨택 대상 — 아직 비용 아님
        for stage in [Stage.CONTACTED, Stage.REPLIED, Stage.NEGOTIATING, Stage.CONTRACTED]:
            services.change_stage(self.p, stage)
        self.assertEqual(CostBook().participation_cost(self.p), 690000)

    def test_missing_rate_is_reported(self):
        Payment.objects.create(participation=self.p, amount=Decimal("1000"), currency="JPY")
        book = CostBook()
        self.assertEqual(book.participation_cost(self.p), 0)
        self.assertEqual(book.missing_rates, {"JPY"})


class PaymentViewTests(PaymentBase):
    def test_add_from_detail_and_list(self):
        res = self.client.post(
            reverse("payments:add", args=[self.p.pk]),
            {"installment": "deposit", "amount": "250", "currency": "USD", "tax_document": "w8ben", "paid_at": "2026-02-01"},
        )
        self.assertRedirects(res, reverse("campaigns:participation", args=[self.p.pk]) + "#payments", fetch_redirect_response=False)
        pay = self.p.payments.get()
        self.assertEqual(pay.amount_krw, 345000)

        res = self.client.get(reverse("payments:list"))
        self.assertContains(res, "345,000")
        self.assertContains(res, "선금 지급 완료")
        self.assertContains(res, "W-8BEN")

        res = self.client.get(reverse("payments:list") + "?download=csv")
        self.assertEqual(res["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("원화 환산액", res.content.decode("utf-8-sig"))

    def test_invalid_payment_shows_error(self):
        res = self.client.post(reverse("payments:add", args=[self.p.pk]), {"amount": "", "currency": "USD"}, follow=True)
        self.assertContains(res, "지급 내역 추가 실패")
        self.assertFalse(Payment.objects.exists())

    def test_rate_list_shows_latest_per_currency(self):
        ExchangeRate.objects.create(currency="USD", rate=Decimal("1420"), effective_date=date(2026, 1, 1) + timedelta(days=60))
        res = self.client.get(reverse("payments:list"))
        self.assertContains(res, "1,420원")
        self.assertNotContains(res, "1,380원")
