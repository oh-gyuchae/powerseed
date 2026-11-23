from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from campaigns import services
from campaigns.models import PIPELINE, Campaign, Client, Participation, Stage, StatusLog
from influencers.models import Influencer


class PipelineTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("manager")
        client = Client.objects.create(name="고객사A")
        self.campaign = Campaign.objects.create(client=client, name="11월 시딩", default_fee=100000)
        self.influencer = Influencer.objects.create(instagram_handle="@Foo.Bar", account_name="푸바")

    def test_add_to_campaign_is_idempotent_and_logged(self):
        p, created = services.add_to_campaign(self.influencer, self.campaign, user=self.user)
        self.assertTrue(created)
        self.assertEqual(p.stage, Stage.CONTACT_TARGET)
        self.assertEqual(p.fee_amount, 100000)
        _, created_again = services.add_to_campaign(self.influencer, self.campaign, user=self.user)
        self.assertFalse(created_again)
        self.assertEqual(StatusLog.objects.filter(participation=p).count(), 1)

    def test_duplicate_participation_rejected(self):
        Participation.objects.create(campaign=self.campaign, influencer=self.influencer)
        with self.assertRaises(IntegrityError):
            Participation.objects.create(campaign=self.campaign, influencer=self.influencer)

    def test_full_pipeline_sets_side_effect_fields(self):
        p, _ = services.add_to_campaign(self.influencer, self.campaign)
        for stage in [Stage.CONTACTED, Stage.SURVEY_SENT, Stage.RESPONDED, Stage.NEGOTIATING, Stage.CONFIRMED]:
            services.change_stage(p, stage, user=self.user)
        self.assertEqual(p.participation_status, Participation.ParticipationStatus.YES)

        for stage in [Stage.VISIT_SCHEDULED, Stage.VISITED, Stage.UPLOADED]:
            services.change_stage(p, stage, user=self.user)
        self.assertIsNotNone(p.uploaded_at)

        services.change_stage(p, Stage.PAYOUT_PENDING, user=self.user)
        self.assertEqual(p.payout_status, Participation.PayoutStatus.PENDING)
        services.change_stage(p, Stage.PAID, user=self.user)
        p.refresh_from_db()
        self.assertEqual(p.payout_status, Participation.PayoutStatus.PAID)
        self.assertIsNotNone(p.paid_at)
        # 1 creation log + 10 transitions
        self.assertEqual(p.status_logs.count(), 11)

    def test_closed_participation_requires_force(self):
        p, _ = services.add_to_campaign(self.influencer, self.campaign)
        services.change_stage(p, Stage.DECLINED)
        self.assertEqual(p.participation_status, Participation.ParticipationStatus.NO)
        with self.assertRaises(ValidationError):
            services.change_stage(p, Stage.CONTACTED)
        services.change_stage(p, Stage.CONTACTED, force=True)
        self.assertEqual(p.stage, Stage.CONTACTED)

    def _walk_to(self, p, last):
        for stage in PIPELINE[1 : PIPELINE.index(last) + 1]:
            services.change_stage(p, stage)

    def test_reopen_paid_clears_paid_at_only(self):
        p, _ = services.add_to_campaign(self.influencer, self.campaign)
        self._walk_to(p, Stage.PAID)
        services.change_stage(p, Stage.PAYOUT_PENDING, force=True)
        p.refresh_from_db()
        self.assertIsNone(p.paid_at)
        self.assertEqual(p.payout_status, Participation.PayoutStatus.PENDING)
        self.assertIsNotNone(p.uploaded_at)  # 업로드 이후 단계이므로 유지

    def test_reopen_before_upload_clears_uploaded_at_and_paid_at(self):
        p, _ = services.add_to_campaign(self.influencer, self.campaign)
        self._walk_to(p, Stage.PAID)
        services.change_stage(p, Stage.VISITED, force=True)
        p.refresh_from_db()
        self.assertIsNone(p.paid_at)
        self.assertIsNone(p.uploaded_at)
        self.assertEqual(p.payout_status, Participation.PayoutStatus.UNPAID)

    def test_back_from_payout_pending_resets_payout_status(self):
        p, _ = services.add_to_campaign(self.influencer, self.campaign)
        self._walk_to(p, Stage.PAYOUT_PENDING)
        services.change_stage(p, Stage.UPLOADED)
        p.refresh_from_db()
        self.assertEqual(p.payout_status, Participation.PayoutStatus.UNPAID)
        self.assertIsNotNone(p.uploaded_at)

    def test_reupload_gets_new_uploaded_at(self):
        p, _ = services.add_to_campaign(self.influencer, self.campaign)
        self._walk_to(p, Stage.UPLOADED)
        services.change_stage(p, Stage.VISITED)
        services.change_stage(p, Stage.UPLOADED)
        self.assertIsNotNone(p.uploaded_at)

    def test_drop_after_upload_keeps_records(self):
        p, _ = services.add_to_campaign(self.influencer, self.campaign)
        self._walk_to(p, Stage.UPLOADED)
        services.change_stage(p, Stage.DROPPED)
        p.refresh_from_db()
        self.assertIsNotNone(p.uploaded_at)

    def test_reopen_declined_resets_participation_status(self):
        p, _ = services.add_to_campaign(self.influencer, self.campaign)
        services.change_stage(p, Stage.DECLINED)
        services.change_stage(p, Stage.CONTACTED, force=True)
        p.refresh_from_db()
        self.assertEqual(p.participation_status, Participation.ParticipationStatus.NO_RESPONSE)

    def test_reopen_declined_straight_to_confirmed_sets_yes(self):
        p, _ = services.add_to_campaign(self.influencer, self.campaign)
        services.change_stage(p, Stage.DECLINED)
        services.change_stage(p, Stage.CONFIRMED, force=True)
        p.refresh_from_db()
        self.assertEqual(p.participation_status, Participation.ParticipationStatus.YES)

    def test_same_stage_is_noop(self):
        p, _ = services.add_to_campaign(self.influencer, self.campaign)
        services.change_stage(p, Stage.CONTACT_TARGET)
        self.assertEqual(p.status_logs.count(), 1)
