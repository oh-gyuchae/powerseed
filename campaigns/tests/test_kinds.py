"""캠페인 유형(방문형/배송형) 분리 — 단계 목록, 단계 전이 동기화, 블랙리스트, 화면."""

from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from campaigns import selectors, services
from campaigns.models import PIPELINES, Campaign, CampaignKind, Client, Participation, Stage
from core.choices import Country, Currency
from influencers.models import Influencer


class KindBase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ops", password="pw-12345")
        self.client.force_login(self.user)
        client = Client.objects.create(name="고객사A")
        self.visit = Campaign.objects.create(client=client, name="방문 캠페인", status=Campaign.Status.ACTIVE)
        self.shipping = Campaign.objects.create(
            client=client, name="해외 캠페인", kind=CampaignKind.SHIPPING, status=Campaign.Status.ACTIVE
        )
        self.inf = Influencer.objects.create(instagram_handle="us_glow", country=Country.US)
        self.p, _ = services.add_to_campaign(self.inf, self.shipping, user=self.user)

    def walk(self, p, last):
        pipeline = PIPELINES[p.campaign.kind]
        for stage in pipeline[pipeline.index(p.stage) + 1 : pipeline.index(last) + 1]:
            services.change_stage(p, stage)


class StageRuleTests(KindBase):
    def test_stages_are_limited_to_the_campaign_kind(self):
        with self.assertRaisesMessage(ValidationError, "배송형 캠페인에 없습니다"):
            services.change_stage(self.p, Stage.SURVEY_SENT)
        visit_p, _ = services.add_to_campaign(self.inf, self.visit)
        with self.assertRaises(ValidationError):
            services.change_stage(visit_p, Stage.SHIPPED)
        with self.assertRaises(ValidationError):
            services.change_stage(visit_p, Stage.NO_RESPONSE)

    def test_shipping_walk_syncs_fields(self):
        self.walk(self.p, Stage.CONTRACTED)
        self.assertEqual(self.p.participation_status, Participation.ParticipationStatus.YES)
        self.walk(self.p, Stage.RECEIVED)
        today = timezone.localdate()
        self.assertEqual((self.p.shipped_at, self.p.received_at), (today, today))
        self.walk(self.p, Stage.PAID)
        self.p.refresh_from_db()
        self.assertEqual(self.p.payout_status, Participation.PayoutStatus.PAID)
        self.assertIsNotNone(self.p.uploaded_at)
        self.assertEqual(self.p.status_logs.count(), len(PIPELINES[CampaignKind.SHIPPING]))

    def test_shipping_reopen_policy(self):
        self.walk(self.p, Stage.PAID)
        services.change_stage(self.p, Stage.UPLOADED, force=True)
        self.p.refresh_from_db()
        # 배송형에는 지급 대기 단계가 없으므로 지급 완료 앞으로 가면 바로 미지급
        self.assertEqual(self.p.payout_status, Participation.PayoutStatus.UNPAID)
        self.assertIsNone(self.p.paid_at)
        self.assertIsNotNone(self.p.uploaded_at)
        services.change_stage(self.p, Stage.CONTRACTED)
        self.p.refresh_from_db()
        self.assertIsNone(self.p.uploaded_at)
        self.assertIsNone(self.p.received_at)
        self.assertIsNone(self.p.shipped_at)

    def test_no_response_is_closed(self):
        services.change_stage(self.p, Stage.CONTACTED)
        services.change_stage(self.p, Stage.NO_RESPONSE)
        self.assertTrue(self.p.is_closed)
        with self.assertRaises(ValidationError):
            services.change_stage(self.p, Stage.CONTACTED)
        services.change_stage(self.p, Stage.CONTACTED, force=True)

    def test_kind_change_blocked_when_stages_do_not_fit(self):
        self.walk(self.p, Stage.SHIPPED)
        self.shipping.kind = CampaignKind.VISIT
        with self.assertRaises(ValidationError):
            self.shipping.full_clean()
        empty = Campaign.objects.create(client=self.visit.client, name="빈 캠페인")
        empty.kind = CampaignKind.SHIPPING
        empty.full_clean()  # 참여 건이 없으면 바꿀 수 있다


class BlacklistTests(KindBase):
    def test_blacklisted_cannot_be_added_but_existing_row_is_returned(self):
        self.inf.is_blacklisted = True
        self.inf.save()
        p, created = services.add_to_campaign(self.inf, self.shipping)
        self.assertEqual((p, created), (self.p, False))
        with self.assertRaisesMessage(ValidationError, "블랙리스트"):
            services.add_to_campaign(self.inf, self.visit)

    def test_add_view_reports_blacklisted(self):
        Influencer.objects.create(instagram_handle="bad_one", is_blacklisted=True)
        res = self.client.post(
            reverse("campaigns:add_influencers", args=[self.visit.pk]), {"handles": "bad_one\nnew_one"}, follow=True
        )
        self.assertContains(res, "블랙리스트라 추가하지 않음: @bad_one")
        self.assertEqual(list(self.visit.participations.values_list("influencer__instagram_handle", flat=True)), ["new_one"])


class OverdueTests(KindBase):
    def test_upload_overdue_only_after_contract_and_before_upload(self):
        past = timezone.now() - timedelta(days=1)
        self.p.upload_due_at = past
        self.p.save()
        self.assertFalse(self.p.is_upload_overdue)  # 아직 계약 전
        self.walk(self.p, Stage.DRAFT_REVIEW)
        self.assertTrue(self.p.is_upload_overdue)
        self.assertEqual(list(selectors.upload_overdue(Participation.objects.all())), [self.p])
        services.change_stage(self.p, Stage.UPLOADED)
        self.assertFalse(self.p.is_upload_overdue)


class ShippingScreenTests(KindBase):
    def test_board_uses_shipping_pipeline(self):
        res = self.client.get(reverse("campaigns:board", args=[self.shipping.pk]))
        self.assertContains(res, "초안 검수")
        self.assertNotContains(res, "방문 예정")
        self.assertContains(res, "거절 · 무응답 · 이탈")

    def test_dashboard_groups_by_kind(self):
        services.add_to_campaign(Influencer.objects.create(instagram_handle="kr_one"), self.visit)
        res = self.client.get(reverse("campaigns:dashboard"))
        self.assertContains(res, "방문형")
        self.assertContains(res, "배송형")
        self.assertContains(res, "계약 이상")

    def test_sheet_columns_follow_kind(self):
        res = self.client.get(reverse("sheets:sheet", args=[self.shipping.pk]))
        self.assertContains(res, "송장번호")
        self.assertContains(res, "업로드 예정일")
        self.assertNotContains(res, "방문 가능일")
        res = self.client.get(reverse("sheets:sheet", args=[self.visit.pk]))
        self.assertNotContains(res, "송장번호")

    def test_sheet_row_saves_shipping_fields_without_touching_hidden_ones(self):
        self.p.product_cost = 35000  # 시트에 열이 없는 필드
        self.p.save()
        res = self.client.post(
            reverse("sheets:row", args=[self.p.pk]),
            {
                "stage": Stage.CONTACTED,
                "participation_status": Participation.ParticipationStatus.NO_RESPONSE,
                "payout_method": "",
                "fee_currency": Currency.USD,
                "fee_amount": "900",
                "tracking_number": "DHL123",
                "revision_count": "2",
                "ad_usage_allowed": "on",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(res.status_code, 200)
        self.p.refresh_from_db()
        self.assertEqual(self.p.stage, Stage.CONTACTED)
        self.assertEqual((self.p.tracking_number, self.p.revision_count, self.p.fee_currency), ("DHL123", 2, "USD"))
        self.assertTrue(self.p.ad_usage_allowed)
        self.assertEqual(self.p.product_cost, 35000)

    def test_detail_form_hides_other_kind_fields(self):
        res = self.client.get(reverse("campaigns:participation", args=[self.p.pk]))
        self.assertContains(res, 'name="tracking_number"')
        self.assertNotContains(res, 'name="available_visit_dates"')
        self.assertContains(res, "콘텐츠 성과")
        self.assertContains(res, "총비용")

    def test_internal_export_highlights_overdue_rows(self):
        self.walk(self.p, Stage.DRAFT_REVIEW)
        self.p.upload_due_at = timezone.now() - timedelta(days=1)
        self.p.save()
        res = self.client.get(reverse("sheets:export", args=[self.shipping.pk, "xlsx"]) + "?scope=internal")
        ws = load_workbook(BytesIO(res.content)).active
        self.assertEqual(ws["A2"].fill.fgColor.rgb[-6:], "FECACA")
        res = self.client.get(reverse("sheets:export", args=[self.shipping.pk, "xlsx"]) + "?scope=client")
        self.assertNotEqual(load_workbook(BytesIO(res.content)).active["A2"].fill.fgColor.rgb[-6:], "FECACA")
