from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from campaigns import selectors, services
from campaigns.models import Campaign, Client, Participation, Stage, StatusLog
from influencers.models import Influencer


class BaseCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ops", password="pw-12345")
        self.client.force_login(self.user)
        self.campaign = Campaign.objects.create(
            client=Client.objects.create(name="고객사A"), name="11월 시딩", status=Campaign.Status.ACTIVE
        )
        self.influencer = Influencer.objects.create(instagram_handle="seed_one", follower_count=12000)
        self.p, _ = services.add_to_campaign(self.influencer, self.campaign, user=self.user)


class AuthTests(TestCase):
    def test_dashboard_requires_login(self):
        res = self.client.get(reverse("campaigns:dashboard"))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse("login"), res.url)


class PageTests(BaseCase):
    def test_dashboard_renders_summary(self):
        res = self.client.get(reverse("campaigns:dashboard"))
        self.assertContains(res, "11월 시딩")

    def test_board_renders_card(self):
        res = self.client.get(reverse("campaigns:board", args=[self.campaign.pk]))
        self.assertContains(res, "@seed_one")
        self.assertContains(res, 'id="board"')

    def test_board_assignee_filter(self):
        other = get_user_model().objects.create_user("other")
        res = self.client.get(reverse("campaigns:board", args=[self.campaign.pk]), {"assignee": other.pk})
        self.assertNotContains(res, "@seed_one")

    def test_board_invalid_assignee_is_ignored(self):
        res = self.client.get(reverse("campaigns:board", args=[self.campaign.pk]), {"assignee": "abc"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "@seed_one")

    def test_board_selected_assignee_option(self):
        res = self.client.get(reverse("campaigns:board", args=[self.campaign.pk]), {"assignee": self.user.pk})
        self.assertContains(res, f'<option value="{self.user.pk}" selected>')


class StageChangeTests(BaseCase):
    def test_htmx_invalid_assignee_is_ignored(self):
        res = self.client.post(
            reverse("campaigns:change_stage", args=[self.p.pk]),
            {"stage": Stage.CONTACTED, "from": "board", "assignee": "abc"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "@seed_one")

    def test_htmx_stage_change_returns_board_partial(self):
        res = self.client.post(
            reverse("campaigns:change_stage", args=[self.p.pk]),
            {"stage": Stage.CONTACTED, "from": "board"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="board"')
        self.assertNotContains(res, "<html")
        self.p.refresh_from_db()
        self.assertEqual(self.p.stage, Stage.CONTACTED)
        self.assertEqual(StatusLog.objects.filter(participation=self.p).count(), 2)

    def test_closed_stage_error_is_shown_on_board(self):
        services.change_stage(self.p, Stage.DECLINED)
        res = self.client.post(
            reverse("campaigns:change_stage", args=[self.p.pk]),
            {"stage": Stage.CONTACTED, "from": "board"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(res, "force=True")
        self.p.refresh_from_db()
        self.assertEqual(self.p.stage, Stage.DECLINED)

    def test_detail_reopen_with_force(self):
        services.change_stage(self.p, Stage.DECLINED)
        res = self.client.post(
            reverse("campaigns:change_stage", args=[self.p.pk]), {"stage": Stage.CONTACTED, "force": "1"}
        )
        self.assertRedirects(res, reverse("campaigns:participation", args=[self.p.pk]))
        self.p.refresh_from_db()
        self.assertEqual(self.p.stage, Stage.CONTACTED)

    def test_invalid_stage(self):
        self.client.post(reverse("campaigns:change_stage", args=[self.p.pk]), {"stage": "nope"})
        self.p.refresh_from_db()
        self.assertEqual(self.p.stage, Stage.CONTACT_TARGET)


class DetailEditTests(BaseCase):
    def test_edit_saves_fee_and_visit_dates(self):
        res = self.client.post(
            reverse("campaigns:participation", args=[self.p.pk]),
            {
                "participation_status": Participation.ParticipationStatus.YES,
                "available_visit_dates": "2026-12-03, 2026-12-01, 2026-12-01",
                "fee_amount": "150000",
                "payout_method": Participation.PayoutMethod.BANK_TRANSFER,
            },
        )
        self.assertEqual(res.status_code, 302)
        self.p.refresh_from_db()
        self.assertEqual(self.p.fee_amount, 150000)
        self.assertEqual(self.p.available_visit_dates, ["2026-12-01", "2026-12-03"])

    def test_bad_visit_date_shows_error(self):
        res = self.client.post(
            reverse("campaigns:participation", args=[self.p.pk]),
            {"participation_status": "yes", "available_visit_dates": "12월 1일"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "날짜 형식이 올바르지 않습니다")


class AddInfluencersTests(BaseCase):
    def test_add_multiple_handles_dedupes(self):
        res = self.client.post(
            reverse("campaigns:add_influencers", args=[self.campaign.pk]),
            {"handles": "@New_One\nhttps://www.instagram.com/new_two/, seed_one, new_one"},
        )
        self.assertEqual(res.status_code, 302)
        handles = set(self.campaign.participations.values_list("influencer__instagram_handle", flat=True))
        self.assertEqual(handles, {"seed_one", "new_one", "new_two"})

    def test_post_or_invalid_entries_are_rejected(self):
        res = self.client.post(
            reverse("campaigns:add_influencers", args=[self.campaign.pk]),
            {"handles": "good_one\nhttps://www.instagram.com/p/ABC123/\n홍 길동"},
            follow=True,
        )
        self.assertContains(res, "인식할 수 없는 항목")
        self.assertContains(res, "https://www.instagram.com/p/ABC123/")
        # all-or-nothing: the valid entry is not added either
        self.assertFalse(Influencer.objects.filter(instagram_handle__in=["good_one", "p"]).exists())


class AdminInlineAddTests(BaseCase):
    def test_inline_add_goes_through_add_to_campaign(self):
        admin = get_user_model().objects.create_superuser("boss", password="pw-12345")
        self.client.force_login(admin)
        newbie = Influencer.objects.create(instagram_handle="newbie")
        prefix = "participations"
        data = {
            "client": self.campaign.client_id,
            "name": self.campaign.name,
            "kind": self.campaign.kind,
            "status": self.campaign.status,
            "default_fee": "80000",
            f"{prefix}-TOTAL_FORMS": "2",
            f"{prefix}-INITIAL_FORMS": "1",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
            f"{prefix}-0-id": self.p.pk,
            f"{prefix}-0-campaign": self.campaign.pk,
            f"{prefix}-0-influencer": self.influencer.pk,
            f"{prefix}-0-participation_status": self.p.participation_status,
            f"{prefix}-0-payout_status": self.p.payout_status,
            f"{prefix}-1-campaign": self.campaign.pk,
            f"{prefix}-1-influencer": newbie.pk,
            f"{prefix}-1-participation_status": Participation.ParticipationStatus.CONSIDERING,
            f"{prefix}-1-payout_status": Participation.PayoutStatus.UNPAID,
        }
        res = self.client.post(reverse("admin:campaigns_campaign_change", args=[self.campaign.pk]), data)
        self.assertEqual(res.status_code, 302)
        p = Participation.objects.get(campaign=self.campaign, influencer=newbie)
        self.assertEqual(p.fee_amount, 80000)
        self.assertEqual(p.assignee, admin)
        self.assertEqual(p.participation_status, Participation.ParticipationStatus.CONSIDERING)
        self.assertEqual(list(p.status_logs.values_list("to_stage", flat=True)), [Stage.CONTACT_TARGET])


class AlertTests(BaseCase):
    def test_overdue_and_no_response_alerts(self):
        now = timezone.now()
        services.change_stage(self.p, Stage.CONFIRMED)
        self.p.confirmed_visit_at = now - timedelta(hours=1)
        self.p.save()

        late = Influencer.objects.create(instagram_handle="late_survey")
        p2, _ = services.add_to_campaign(late, self.campaign)
        services.change_stage(p2, Stage.SURVEY_SENT)
        StatusLog.objects.filter(participation=p2, to_stage=Stage.SURVEY_SENT).update(
            created_at=now - timedelta(days=4)
        )
        # An unrelated edit must not reset the no-response timer.
        p2.notes = "메모 수정"
        p2.save()

        alerts = selectors.dashboard_alerts(now=now)
        self.assertEqual(list(alerts["visit_overdue"]), [self.p])
        self.assertEqual(list(alerts["survey_no_response"]), [p2])
        self.assertEqual(list(alerts["upload_overdue"]), [])
