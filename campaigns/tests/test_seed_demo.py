import io

from django.core.management import call_command
from django.test import TestCase, override_settings

from campaigns.models import Campaign, CampaignKind, Participation
from messaging.models import MessageTemplate
from performance.models import ContentPost


@override_settings(DEBUG=True)
class SeedDemoTests(TestCase):
    def test_seed_demo_runs_and_is_idempotent(self):
        call_command("seed_demo", stdout=io.StringIO())
        call_command("seed_demo", stdout=io.StringIO())
        self.assertEqual(Campaign.objects.filter(kind=CampaignKind.VISIT).count(), 1)
        self.assertEqual(Campaign.objects.filter(kind=CampaignKind.SHIPPING).count(), 1)
        self.assertEqual(Participation.objects.filter(campaign__kind=CampaignKind.VISIT).count(), 13)
        self.assertEqual(Participation.objects.filter(campaign__kind=CampaignKind.SHIPPING).count(), 9)
        self.assertEqual(ContentPost.objects.count(), 3)
        self.assertIn("{{설문링크}}", MessageTemplate.objects.get(name="설문 안내").body)
