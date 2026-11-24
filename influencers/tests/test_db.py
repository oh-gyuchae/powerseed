"""시트 ① 인플루언서 DB — ID 자동 부여, 목록·내보내기."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from influencers.models import Influencer


class CodeTests(TestCase):
    def test_code_is_assigned_per_country_and_stays(self):
        a = Influencer.objects.create(instagram_handle="us_a", country="US")
        b = Influencer.objects.create(instagram_handle="us_b", country="US")
        j = Influencer.objects.create(instagram_handle="jp_a", country="JP")
        self.assertEqual((a.code, b.code, j.code), ("US-001", "US-002", "JP-001"))
        a.country = "JP"
        a.save()
        self.assertEqual(a.code, "US-001")  # 한 번 부여된 ID는 바뀌지 않는다

    def test_no_country_no_code_and_update_fields_save(self):
        k = Influencer.objects.create(instagram_handle="kr_a")
        self.assertEqual(k.code, "")
        k.country = "KR"
        k.save(update_fields=["country"])
        k.refresh_from_db()
        self.assertEqual(k.code, "KR-001")

    def test_gaps_continue_from_max(self):
        Influencer.objects.create(instagram_handle="us_a", country="US")
        b = Influencer.objects.create(instagram_handle="us_b", country="US")
        Influencer.objects.filter(pk=b.pk).update(code="US-007")
        self.assertEqual(Influencer.objects.create(instagram_handle="us_c", country="US").code, "US-008")


class ListTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("ops", password="pw-12345"))
        Influencer.objects.create(instagram_handle="us_glow", country="US", category="skincare", agency="Glow Agency")
        Influencer.objects.create(instagram_handle="jp_bad", country="JP", is_blacklisted=True)

    def test_filters(self):
        res = self.client.get(reverse("influencers:list") + "?country=US")
        self.assertContains(res, "@us_glow")
        self.assertNotContains(res, "@jp_bad")
        res = self.client.get(reverse("influencers:list") + "?blacklist=only")
        self.assertContains(res, "@jp_bad")
        self.assertNotContains(res, "@us_glow")
        res = self.client.get(reverse("influencers:list") + "?q=US-001")
        self.assertContains(res, "@us_glow")

    def test_export(self):
        res = self.client.get(reverse("influencers:list") + "?download=csv")
        text = res.content.decode("utf-8-sig")
        self.assertIn("인플루언서 ID", text)
        self.assertIn("US-001", text)
        self.assertIn("Glow Agency", text)
