from django.test import SimpleTestCase, TestCase

from influencers.models import Influencer, is_valid_handle, normalize_handle


class NormalizeHandleTests(SimpleTestCase):
    def test_variants(self):
        for raw in ["@Foo.Bar", "foo.bar", " https://www.instagram.com/Foo.Bar/?hl=ko ", "instagram.com/foo.bar"]:
            self.assertEqual(normalize_handle(raw), "foo.bar", raw)

    def test_non_profile_urls_yield_empty(self):
        for raw in [
            "https://www.instagram.com/p/ABC123/",
            "https://instagram.com/reel/XYZ?igsh=1",
            "instagram.com/explore/tags/cafe/",
            "https://www.instagram.com/",
        ]:
            self.assertEqual(normalize_handle(raw), "", raw)

    def test_story_url_yields_owner(self):
        self.assertEqual(normalize_handle("https://www.instagram.com/stories/Foo.Bar/3141592/"), "foo.bar")

    def test_is_valid_handle(self):
        for ok in ["foo.bar", "a_1", "x" * 30]:
            self.assertTrue(is_valid_handle(ok), ok)
        for bad in ["", "홍길동", "foo bar", "x" * 31, "foo-bar"]:
            self.assertFalse(is_valid_handle(bad), bad)


class InfluencerTests(TestCase):
    def test_save_normalizes_and_fills_url(self):
        inf = Influencer.objects.create(instagram_handle="@Seed_Girl")
        self.assertEqual(inf.instagram_handle, "seed_girl")
        self.assertEqual(inf.account_url, "https://www.instagram.com/seed_girl/")
