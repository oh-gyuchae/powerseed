from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from campaigns import services
from campaigns.models import Campaign, Client, Participation, Stage, StatusLog
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

    def test_same_stage_is_noop(self):
        p, _ = services.add_to_campaign(self.influencer, self.campaign)
        services.change_stage(p, Stage.CONTACT_TARGET)
        self.assertEqual(p.status_logs.count(), 1)
