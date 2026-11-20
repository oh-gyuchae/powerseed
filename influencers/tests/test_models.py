from django.test import SimpleTestCase, TestCase

from influencers.models import Influencer, normalize_handle


class NormalizeHandleTests(SimpleTestCase):
    def test_variants(self):
        for raw in ["@Foo.Bar", "foo.bar", " https://www.instagram.com/Foo.Bar/?hl=ko ", "instagram.com/foo.bar"]:
            self.assertEqual(normalize_handle(raw), "foo.bar", raw)


class InfluencerTests(TestCase):
    def test_save_normalizes_and_fills_url(self):
        inf = Influencer.objects.create(instagram_handle="@Seed_Girl")
        self.assertEqual(inf.instagram_handle, "seed_girl")
        self.assertEqual(inf.account_url, "https://www.instagram.com/seed_girl/")
