"""발굴 흐름: Apify 2단계 수집, insta-finder 파일 올리기, 인플루언서 DB 자동 등록·카테고리 분류."""

import io
import json

import httpx
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from campaigns.models import Campaign, Client
from collector import services
from collector.adapters import CollectorError
from collector.adapters.apify import BASE_URL, ApifyClient, merge_profiles, owners_from_posts
from collector.classify import guess_category
from collector.importers import parse_csv, parse_xlsx, to_count
from collector.models import Candidate, HashtagJob
from influencers.models import Category, Influencer

POSTS = [
    {"ownerUsername": "Glow.Kim", "ownerFullName": "글로우", "videoPlayCount": 5000, "likesCount": 300, "commentsCount": 10, "url": "https://www.instagram.com/reel/a/"},
    {"ownerUsername": "glow.kim", "videoPlayCount": 9000, "likesCount": 500, "commentsCount": 20, "url": "https://www.instagram.com/reel/b/"},
    {"ownerUsername": "seoul_eats", "videoViewCount": 1200, "likesCount": 80, "url": "https://www.instagram.com/p/c/"},
    {"ownerUsername": ""},
]
PROFILES = [
    {"username": "glow.kim", "followersCount": 15000, "biography": "스킨케어 리뷰", "businessCategoryName": "Blogger"},
    {"username": "seoul_eats", "followersCount": 3200, "biography": "서울 맛집 기록"},
]


class FakeApify:
    """Apify REST API 흉내: 실행 2개(게시물 → 프로필)를 차례로 SUCCEEDED로 돌려준다."""

    def __init__(self, status="SUCCEEDED"):
        self.status = status
        self.started = []

    def handler(self, request: httpx.Request):
        path = request.url.path.removeprefix("/v2")
        if request.method == "POST" and path.startswith("/acts/"):
            self.started.append((path, json.loads(request.content)))
            return httpx.Response(201, json={"data": {"id": f"run{len(self.started)}"}})
        if path.startswith("/actor-runs/"):
            run_id = path.rsplit("/", 1)[1]
            return httpx.Response(200, json={"data": {"status": self.status, "defaultDatasetId": f"ds-{run_id}"}})
        if path == "/datasets/ds-run1/items":
            return httpx.Response(200, json=POSTS)
        if path == "/datasets/ds-run2/items":
            return httpx.Response(200, json=PROFILES)
        return httpx.Response(404, text="not found")

    def client(self):
        return ApifyClient(http=httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(self.handler)))


class ParsingTests(TestCase):
    def test_owners_keep_best_post_and_limit(self):
        owners = owners_from_posts(POSTS, limit=10)
        self.assertEqual([o["handle"] for o in owners], ["glow.kim", "seoul_eats"])
        self.assertEqual((owners[0]["views"], owners[0]["likes"], owners[0]["posts_found"]), (9000, 500, 2))
        self.assertEqual(len(owners_from_posts(POSTS, limit=1)), 1)

    def test_merge_profiles_keeps_accounts_without_profile(self):
        merged = merge_profiles(owners_from_posts(POSTS, 10) + [{"handle": "ghost"}], PROFILES)
        self.assertEqual(merged[0]["follower_count"], 15000)
        self.assertIsNone(merged[2]["follower_count"])

    def test_to_count(self):
        self.assertEqual([to_count(v) for v in ("948K", "1.2만", "2,918", "3천", "1.1M", "", None, 77)],
                         [948000, 12000, 2918, 3000, 1100000, None, None, 77])

    def test_guess_category(self):
        self.assertEqual(guess_category("성수카페"), Category.FOOD)
        self.assertEqual(guess_category("데일리", "", "헤어 디자이너"), Category.HAIR)
        self.assertEqual(guess_category("xyz", ""), "")


def _xlsx(rows):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


HEADER = ["계정", "조회수", "좋아요", "댓글", "공유", "팔로워", "팔로잉", "게시물수", "참여율(%)", "팔로워대비조회수", "계정 링크"]
INSTA_FINDER_XLSX = [
    ["#용산맛집"], HEADER,
    ["yongsan_foodie", "948K", "1.2만", "320", "15", 25000, 300, 120, 2.4, 37.9, "https://www.instagram.com/yongsan_foodie/"],
    ["Cafe.Day", "2,918", "100", "4", "", 1800, 50, 40, 4.0, 1.6, ""],
    [], ["#용산카페"], HEADER,
    ["cafe.day", "5천", "90", "2", "", 1800, 50, 40, 1.9, 2.8, ""],
    [], ["⚠️ 수집 실패 (재시도 필요): 용산빵집"],
]


class ImportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ops", password="pw-12345")
        self.client.force_login(self.user)
        self.campaign = Campaign.objects.create(client=Client.objects.create(name="고객사"), name="용산 시딩")

    def test_parse_xlsx_sections(self):
        groups = parse_xlsx(_xlsx(INSTA_FINDER_XLSX))
        self.assertEqual(list(groups), ["#용산맛집", "#용산카페"])
        first = groups["#용산맛집"][0]
        self.assertEqual((first["handle"], first["views"], first["likes"], first["follower_count"]), ("yongsan_foodie", 948000, 12000, 25000))

    def test_parse_csv(self):
        content = "hashtag,username,views,likes,comments,shares,followers,following,posts,engagement_rate(%),views_per_follower\n" \
                  "용산맛집,yongsan_foodie,948K,1.2만,320,15,25000,300,120,2.4,37.9\n"
        groups = parse_csv(content.encode("utf-8-sig"))
        self.assertEqual(groups["용산맛집"][0]["engagement_rate"], 2.4)
        with self.assertRaises(CollectorError):
            parse_csv(b"a,b\n1,2\n")

    def test_upload_creates_jobs_and_registers_influencers(self):
        Influencer.objects.create(instagram_handle="cafe.day", category=Category.LIFESTYLE)  # 사람이 넣은 값은 유지
        upload = SimpleUploadedFile("result.xlsx", _xlsx(INSTA_FINDER_XLSX))
        res = self.client.post(reverse("collector:jobs"), {"action": "upload", "file": upload, "campaign": self.campaign.pk})
        self.assertRedirects(res, reverse("collector:jobs"))
        jobs = HashtagJob.objects.order_by("pk")
        self.assertEqual([(j.hashtag, j.source, j.status, j.result_count) for j in jobs],
                         [("용산맛집", "upload", "done", 2), ("용산카페", "upload", "done", 1)])
        self.assertEqual(jobs[0].campaign, self.campaign)
        foodie = Influencer.objects.get(instagram_handle="yongsan_foodie")
        self.assertEqual((foodie.follower_count, foodie.category, foodie.source), (25000, Category.FOOD, "collector"))
        self.assertEqual(Influencer.objects.get(instagram_handle="cafe.day").category, Category.LIFESTYLE)
        self.assertFalse(Candidate.objects.filter(influencer__isnull=True).exists())
        self.assertEqual(self.campaign.participations.count(), 0)  # 캠페인 추가는 검토에서 고른 것만

        review = self.client.get(reverse("collector:review", args=[jobs[0].pk]))
        self.assertContains(review, "948,000")
        self.assertContains(review, f'value="{self.campaign.pk}" selected')

    def test_upload_rejects_other_files(self):
        res = self.client.post(reverse("collector:jobs"), {"action": "upload", "file": SimpleUploadedFile("a.txt", b"x")}, follow=True)
        self.assertContains(res, "xlsx 또는 csv")
        self.assertFalse(HashtagJob.objects.exists())


@override_settings(APIFY_TOKEN="tok")
class ApifyFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ops", password="pw-12345")

    def test_two_stage_flow_registers_influencers(self):
        fake = FakeApify()
        client = fake.client()
        job = services.start_job("성수카페", 10, self.user, client=client)
        self.assertEqual((job.source, job.status, job.external["stage"]), ("apify", "running", "posts"))
        self.assertEqual(fake.started[0][1], {"hashtags": ["성수카페"], "resultsLimit": 20})

        job = services.poll_job(job.pk, client=client)  # 게시물 끝 → 프로필 실행
        self.assertEqual((job.status, job.external["stage"]), ("running", "profiles"))
        self.assertEqual(fake.started[1][1], {"usernames": ["glow.kim", "seoul_eats"]})

        job = services.poll_job(job.pk, client=client)  # 프로필 끝 → 완료
        self.assertEqual((job.status, job.result_count), ("done", 2))
        self.assertNotIn("accounts", job.external)
        glow = Influencer.objects.get(instagram_handle="glow.kim")
        self.assertEqual((glow.follower_count, glow.category), (15000, Category.FOOD))  # 해시태그가 먼저
        self.assertEqual(job.candidates.get(handle="glow.kim").raw["views"], 9000)

        services.poll_job(job.pk, client=client)  # 끝난 작업은 다시 진행하지 않음
        self.assertEqual(Candidate.objects.count(), 2)

    def test_running_and_failed_runs(self):
        fake = FakeApify(status="RUNNING")
        job = services.start_job("성수카페", 5, client=fake.client())
        self.assertEqual(services.poll_job(job.pk, client=fake.client()).status, "running")
        fake.status = "FAILED"
        job = services.poll_job(job.pk, client=fake.client())
        self.assertEqual(job.status, "failed")
        self.assertIn("FAILED", job.error)

    def test_start_error_marks_failed(self):
        client = ApifyClient(http=httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad token"))))
        job = services.start_job("성수카페", 5, client=client)
        self.assertEqual(job.status, "failed")
        self.assertIn("401", job.error)

    def test_job_category_overrides_guess(self):
        fake = FakeApify()
        job = services.start_job("성수카페", 10, category=Category.SKINCARE, client=fake.client())
        services.poll_job(job.pk, client=fake.client())
        services.poll_job(job.pk, client=fake.client())
        self.assertEqual(Influencer.objects.get(instagram_handle="seoul_eats").category, Category.SKINCARE)

    def test_screens_show_running_job(self):
        self.client.force_login(self.user)
        job = HashtagJob.objects.create(hashtag="성수카페", source="apify", status="running", external={"stage": "posts", "run_id": "x"})
        res = self.client.get(reverse("collector:jobs"))
        self.assertContains(res, 'hx-trigger="every 5s"')
        res = self.client.get(reverse("collector:review", args=[job.pk]))
        self.assertContains(res, "수집 중입니다")
