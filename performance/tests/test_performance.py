
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from campaigns import services
from campaigns.models import Campaign, CampaignKind, Client, Stage
from influencers.models import Influencer
from performance import selectors
from performance.models import ContentPost


def walk(p, stages):
    for stage in stages:
        services.change_stage(p, stage)


SHIP_TO_CONTRACT = [Stage.CONTACTED, Stage.REPLIED, Stage.NEGOTIATING, Stage.CONTRACTED]


class PostMetricTests(TestCase):
    def test_checkpoint_and_engagement_rate(self):
        post = ContentPost(views_d7=1000, likes_d7=50, comments_d7=10, saves_d7=20, shares_d7=20)
        self.assertEqual((post.checkpoint, post.views, post.engagement_rate), ("d7", 1000, 10.0))
        post.views_d30, post.likes_d30 = 4000, 200
        self.assertEqual((post.checkpoint, post.views, post.engagement_rate), ("d30", 4000, 5.0))
        self.assertIsNone(ContentPost().engagement_rate)


class ReportBase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ops", password="pw-12345")
        self.client.force_login(self.user)
        client = Client.objects.create(name="고객사A")
        self.campaign = Campaign.objects.create(client=client, name="해외", kind=CampaignKind.SHIPPING)
        self.us = Influencer.objects.create(instagram_handle="us_glow", country="US")
        self.us2 = Influencer.objects.create(instagram_handle="us_two", country="US")
        self.jp = Influencer.objects.create(instagram_handle="jp_one", country="JP")

        self.p, _ = services.add_to_campaign(self.us, self.campaign)
        walk(self.p, SHIP_TO_CONTRACT)
        self.p.fee_amount, self.p.fee_currency = 100000, "KRW"
        self.p.product_cost = 20000
        self.p.save()  # 총비용 120,000원
        ContentPost.objects.create(participation=self.p, url="https://instagram.com/reel/a/", views_d7=10000, revenue=240000)
        ContentPost.objects.create(participation=self.p, url="https://instagram.com/reel/b/", views_d7=2000, likes_d7=100)

        declined, _ = services.add_to_campaign(self.us2, self.campaign)
        walk(declined, [Stage.CONTACTED, Stage.DECLINED])  # 거절도 회신으로 센다
        silent, _ = services.add_to_campaign(self.jp, self.campaign)
        walk(silent, [Stage.CONTACTED, Stage.NO_RESPONSE])
        # 컨택 대상에 머문 건은 섭외 수에서 빠진다
        services.add_to_campaign(Influencer.objects.create(instagram_handle="kr_wait", country="KR"), self.campaign)


class MetricsTests(ReportBase):
    def test_cost_is_split_across_posts(self):
        rows = {r.url: r for r in selectors.with_metrics(selectors.posts(self.campaign.pk))}
        a, b = rows["https://instagram.com/reel/a/"], rows["https://instagram.com/reel/b/"]
        self.assertEqual((a.cost_krw, b.cost_krw), (60000, 60000))
        self.assertEqual((a.cpv, a.cpm, a.roas), (6.0, 6000, 400.0))
        self.assertEqual((b.cpv, b.roas), (30.0, None))

    def test_campaign_performance_uses_totals(self):
        rows, missing = selectors.campaign_performance()
        row = rows[0]
        self.assertEqual((row.cost_krw, row.views, row.revenue, row.posts, row.contracted), (120000, 12000, 240000, 2, 1))
        self.assertEqual((row.cpv, row.roas), (10.0, 200.0))
        self.assertEqual(missing, set())

    def test_foreign_fee_is_left_out_and_reported(self):
        self.p.fee_amount, self.p.fee_currency = 100, "USD"
        self.p.save()
        rows, missing = selectors.campaign_performance()
        self.assertEqual((rows[0].cost_krw, missing), (20000, {"USD"}))

    def test_uncommitted_fee_is_not_cost(self):
        services.change_stage(self.p, Stage.NEGOTIATING)
        rows, _ = selectors.campaign_performance()
        self.assertEqual(rows[0].cost_krw, 20000)

    def test_country_funnel(self):
        funnel = {r["country"]: r for r in selectors.country_funnel()}
        self.assertNotIn("한국", funnel)
        us = funnel["미국"]
        self.assertEqual((us["contacted"], us["replied"], us["contracted"]), (2, 2, 1))
        self.assertEqual((us["reply_rate"], us["contract_rate"]), (100.0, 50.0))
        jp = funnel["일본"]
        self.assertEqual((jp["contacted"], jp["replied"], jp["reply_rate"], jp["contract_rate"]), (1, 0, 0.0, None))

    def test_funnel_counts_reached_stages_even_after_reopen(self):
        services.change_stage(self.p, Stage.DROPPED)
        self.assertEqual({r["country"]: r for r in selectors.country_funnel()}["미국"]["contracted"], 1)

    def test_top_influencers(self):
        other = Campaign.objects.create(client=self.campaign.client, name="해외2", kind=CampaignKind.SHIPPING)
        p2, _ = services.add_to_campaign(self.jp, other)
        walk(p2, SHIP_TO_CONTRACT)
        p2.fee_amount, p2.fee_currency = 10000, "KRW"
        p2.save()
        ContentPost.objects.create(participation=p2, url="https://instagram.com/reel/c/", views_d7=5000)

        by_cpv = selectors.top_influencers("cpv")
        self.assertEqual([r.influencer for r in by_cpv], [self.jp, self.us])  # 2원 < 10원
        self.assertEqual([r.influencer for r in selectors.top_influencers("roas")], [self.us])
        self.assertEqual(selectors.top_influencers("views")[0].views, 12000)


class ScreenTests(ReportBase):
    def test_report_renders(self):
        res = self.client.get(reverse("performance:report"))
        self.assertContains(res, "국가별 섭외")
        self.assertContains(res, "120,000")
        self.assertContains(res, "200.0%")
        res = self.client.get(reverse("performance:report") + "?kind=visit&top=roas")
        self.assertEqual(res.status_code, 200)

    def test_content_list_and_client_export_drops_cost(self):
        res = self.client.get(reverse("performance:list") + f"?campaign={self.campaign.pk}")
        self.assertContains(res, "@us_glow")
        self.assertContains(res, "60,000")
        internal = self.client.get(reverse("performance:list") + "?download=csv&scope=internal").content.decode("utf-8-sig")
        client = self.client.get(reverse("performance:list") + "?download=csv&scope=client").content.decode("utf-8-sig")
        self.assertIn("CPV", internal)
        self.assertNotIn("CPV", client)
        self.assertIn("참여율", client)

    def test_add_post_from_detail(self):
        res = self.client.post(
            reverse("performance:add", args=[self.p.pk]),
            {"url": "https://instagram.com/reel/z/", "format": "reels", "views_d7": "300"},
        )
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.p.posts.count(), 3)
        res = self.client.post(reverse("performance:add", args=[self.p.pk]), {"url": "not-a-url", "format": "reels"}, follow=True)
        self.assertContains(res, "게시물 추가 실패")
