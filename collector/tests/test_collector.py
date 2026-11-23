from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from campaigns.models import Campaign, Client, Participation, Stage, StatusLog
from collector.adapters import CollectorError
from collector.adapters.scraper import ScraperAdapter, parse_followers
from collector.models import Candidate, HashtagJob
from collector.services import approve_candidates, normalize_hashtag, reject_candidates, run_job, start_job
from influencers.models import Influencer

ROWS = [
    {"handle": "@Cafe.Lover", "account_name": "카페러버", "follower_count": "12,300"},
    {"username": "https://instagram.com/seoul_eats/", "follower_count": 5000},
    {"handle": "cafe.lover", "follower_count": 1},  # 중복
    {"handle": "한글계정"},  # 형식 오류
    {"handle": "https://www.instagram.com/p/abc/"},  # 게시물 URL
]
calls = {"count": 0}


def fake_scrape(hashtag, limit):
    return iter(ROWS)


def flaky_scrape(hashtag, limit):
    calls["count"] += 1
    if calls["count"] < 2:
        raise RuntimeError("429")
    return [{"handle": "retry_ok"}]


def broken_scrape(hashtag, limit):
    raise RuntimeError("blocked")


FAKE = "collector.tests.test_collector.fake_scrape"


@override_settings(COLLECTOR_SCRAPER=FAKE, COLLECTOR_MAX_ATTEMPTS=2, COLLECTOR_RETRY_DELAY=0)
class CollectorServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("op", password="pw")
        client = Client.objects.create(name="고객사")
        self.campaign = Campaign.objects.create(client=client, name="캠페인", default_fee=100000)

    def test_normalize_hashtag(self):
        self.assertEqual(normalize_hashtag(" #성수Cafe_1 "), "성수cafe_1")
        self.assertEqual(normalize_hashtag("성수 카페"), "")
        self.assertEqual(normalize_hashtag("#"), "")

    def test_parse_followers(self):
        self.assertEqual(parse_followers("12,300"), 12300)
        self.assertIsNone(parse_followers("1.2만"))
        self.assertIsNone(parse_followers(True))
        self.assertIsNone(parse_followers(-1))
        self.assertIsNone(parse_followers(2**40))

    def test_job_loads_normalized_unique_candidates(self):
        job = start_job("성수카페", 10, self.user)
        self.assertEqual(job.status, HashtagJob.Status.DONE)
        self.assertEqual(set(job.candidates.values_list("handle", flat=True)), {"cafe.lover", "seoul_eats"})
        self.assertEqual((job.result_count, job.skipped_count), (2, 3))
        self.assertEqual(job.candidates.get(handle="cafe.lover").follower_count, 12300)

    def test_limit_is_enforced(self):
        job = start_job("성수카페", 1, self.user)
        self.assertEqual(job.result_count, 1)

    @override_settings(COLLECTOR_SCRAPER="collector.tests.test_collector.flaky_scrape")
    def test_retries_then_succeeds(self):
        calls["count"] = 0
        job = start_job("retry", 10, self.user)
        self.assertEqual(job.status, HashtagJob.Status.DONE)
        self.assertEqual(calls["count"], 2)

    @override_settings(COLLECTOR_SCRAPER="collector.tests.test_collector.broken_scrape")
    def test_failure_is_recorded(self):
        job = start_job("broken", 10, self.user)
        self.assertEqual(job.status, HashtagJob.Status.FAILED)
        self.assertIn("blocked", job.error)

    @override_settings(COLLECTOR_SCRAPER="")
    def test_unconfigured_raises(self):
        with self.assertRaises(CollectorError):
            ScraperAdapter().collect("x", 1)

    def test_done_job_is_not_rerun(self):
        job = start_job("성수카페", 10, self.user)
        with mock.patch("collector.services.get_adapter") as adapter:
            run_job(job.pk)
        adapter.assert_not_called()

    def test_approve_creates_influencer_and_participation_idempotently(self):
        job = start_job("성수카페", 10, self.user)
        selected = job.candidates.filter(handle="cafe.lover")
        self.assertEqual(approve_candidates(selected, self.campaign, user=self.user), (1, 0))
        self.assertEqual(approve_candidates(selected, self.campaign, user=self.user), (0, 1))

        influencer = Influencer.objects.get(instagram_handle="cafe.lover")
        self.assertEqual(influencer.source, Influencer.Source.COLLECTOR)
        self.assertEqual(influencer.discovered_hashtags, ["성수카페"])
        participation = Participation.objects.get(influencer=influencer, campaign=self.campaign)
        self.assertEqual(participation.stage, Stage.CONTACT_TARGET)
        self.assertEqual(participation.fee_amount, 100000)
        self.assertEqual(StatusLog.objects.filter(participation=participation).count(), 1)
        self.assertEqual(selected.get().review_status, Candidate.ReviewStatus.APPROVED)

    def test_approve_keeps_existing_values_and_fills_blanks(self):
        existing = Influencer.objects.create(
            instagram_handle="cafe.lover", account_name="직접 입력", discovered_hashtags=["기존"]
        )
        job = start_job("성수카페", 10, self.user)
        approve_candidates(job.candidates.filter(handle="cafe.lover"), self.campaign, user=self.user)
        existing.refresh_from_db()
        self.assertEqual(existing.account_name, "직접 입력")
        self.assertEqual(existing.follower_count, 12300)
        self.assertEqual(existing.source, Influencer.Source.MANUAL)
        self.assertEqual(existing.discovered_hashtags, ["기존", "성수카페"])

    def test_reject_does_not_touch_approved(self):
        job = start_job("성수카페", 10, self.user)
        approve_candidates(job.candidates.filter(handle="cafe.lover"), self.campaign, user=self.user)
        self.assertEqual(reject_candidates(job.candidates.all()), 1)
        self.assertEqual(job.candidates.get(handle="cafe.lover").review_status, Candidate.ReviewStatus.APPROVED)


@override_settings(COLLECTOR_SCRAPER=FAKE, COLLECTOR_MAX_ATTEMPTS=1, COLLECTOR_RETRY_DELAY=0)
class CollectorViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("op", password="pw")
        self.client.force_login(self.user)
        client = Client.objects.create(name="고객사")
        self.campaign = Campaign.objects.create(client=client, name="캠페인")

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("collector:jobs")).status_code, 302)

    def test_hashtag_to_promotion_e2e(self):
        response = self.client.post(reverse("collector:jobs"), {"hashtag": "#성수카페", "limit": 10}, follow=True)
        self.assertContains(response, "@cafe.lover")
        job = HashtagJob.objects.get()
        ids = list(job.candidates.values_list("pk", flat=True))
        response = self.client.post(
            reverse("collector:bulk", args=[job.pk]),
            {"ids": ids, "campaign": self.campaign.pk, "action": "approve"},
            follow=True,
        )
        self.assertContains(response, "2명 추가")
        self.assertEqual(self.campaign.participations.count(), 2)

    def test_invalid_hashtag_creates_no_job(self):
        response = self.client.post(reverse("collector:jobs"), {"hashtag": "성수 카페", "limit": 10})
        self.assertContains(response, "공백 없이")
        self.assertFalse(HashtagJob.objects.exists())

    @override_settings(COLLECTOR_SCRAPER="")
    def test_unconfigured_blocks_job(self):
        response = self.client.post(reverse("collector:jobs"), {"hashtag": "cafe", "limit": 10})
        self.assertContains(response, "연결되지 않아")
        self.assertFalse(HashtagJob.objects.exists())

    def test_bulk_ignores_other_jobs_candidates(self):
        job = start_job("a", 10, self.user)
        other = start_job("b", 10, self.user)
        foreign = other.candidates.first()
        self.client.post(
            reverse("collector:bulk", args=[job.pk]),
            {"ids": [foreign.pk], "campaign": self.campaign.pk, "action": "approve"},
        )
        foreign.refresh_from_db()
        self.assertEqual(foreign.review_status, Candidate.ReviewStatus.PENDING)
        self.assertEqual(self.campaign.participations.count(), 0)

    def test_closed_campaign_rejected(self):
        self.campaign.status = Campaign.Status.DONE
        self.campaign.save()
        job = start_job("a", 10, self.user)
        ids = list(job.candidates.values_list("pk", flat=True))
        self.client.post(
            reverse("collector:bulk", args=[job.pk]),
            {"ids": ids, "campaign": self.campaign.pk, "action": "approve"},
        )
        self.assertEqual(self.campaign.participations.count(), 0)

    def test_filter_by_followers_keeps_query_after_bulk(self):
        job = start_job("a", 10, self.user)
        url = reverse("collector:review", args=[job.pk])
        response = self.client.get(url, {"status": "all", "min_followers": 10000})
        self.assertContains(response, "@cafe.lover")
        self.assertNotContains(response, "@seoul_eats")
        bulk = reverse("collector:bulk", args=[job.pk]) + "?status=all&min_followers=10000"
        response = self.client.post(bulk, {"ids": [job.candidates.first().pk], "action": "reject"})
        self.assertRedirects(response, f"{url}?status=all&min_followers=10000")
