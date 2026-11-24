import hashlib
import hmac
import json
from datetime import timedelta
from unittest import mock

import httpx
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from campaigns import services as campaign_services
from campaigns.models import Campaign, Client, Stage
from influencers.models import Influencer
from messaging import services
from messaging.models import Channel, InstagramThread, Message, MessageTemplate
from messaging.providers import ProviderError
from messaging.providers.instagram import InstagramProvider
from surveys.models import CampaignForm, FormQuestion, Target

GMAIL = {"GMAIL_ADDRESS": "seeding@agency.test", "GMAIL_APP_PASSWORD": "app-pw", "GMAIL_FROM_NAME": "에이전시"}
IG = {"INSTAGRAM_ACCESS_TOKEN": "tok", "INSTAGRAM_ACCOUNT_ID": "me", "META_APP_SECRET": "s3cret", "META_WEBHOOK_VERIFY_TOKEN": "verify-me"}


class MessagingBase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ops", password="pw-12345")
        self.client.force_login(self.user)
        self.campaign = Campaign.objects.create(
            client=Client.objects.create(name="고객사A"), name="12월 시딩", visit_location="성수 카페"
        )
        self.inf = Influencer.objects.create(instagram_handle="cafe_lover", account_name="카페러버", email="lover@example.com")
        self.p, _ = campaign_services.add_to_campaign(self.inf, self.campaign, user=self.user)
        cf = CampaignForm.objects.create(campaign=self.campaign, form_id="x" * 30, responder_uri="https://docs.google.com/forms/d/e/R/viewform")
        FormQuestion.objects.create(form=cf, question_id="0a1b", title="참여 코드", target=Target.PARTICIPATION_CODE)


class TemplateTests(MessagingBase):
    def test_render_variables(self):
        text = services.render_template("{{이름}}님({{계정}}) {{캠페인}} @ {{방문장소}}\n{{설문링크}}", self.p)
        self.assertIn("카페러버님(@cafe_lover) 12월 시딩 @ 성수 카페", text)
        self.assertIn(f"entry.{int('0a1b', 16)}={self.p.survey_token}", text)


@override_settings(**GMAIL)
class GmailTests(MessagingBase):
    def test_send_logs_and_moves_stage_when_survey_link_included(self):
        body = services.render_template("설문 부탁드려요 {{설문링크}}", self.p)
        msg = services.send_message(self.p, Channel.EMAIL, subject="12월 시딩 안내", body=body, user=self.user)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["lover@example.com"])
        self.assertIn("seeding@agency.test", sent.from_email)
        self.assertEqual(msg.status, Message.Status.SENT)
        self.assertTrue(msg.external_id.startswith("<"))
        self.p.refresh_from_db()
        self.assertEqual(self.p.stage, Stage.SURVEY_SENT)

    def test_plain_message_keeps_stage(self):
        services.send_message(self.p, Channel.EMAIL, subject="안내", body="안녕하세요")
        self.p.refresh_from_db()
        self.assertEqual(self.p.stage, Stage.CONTACT_TARGET)

    def test_no_email_or_subject(self):
        with self.assertRaisesMessage(ProviderError, "메일 제목"):
            services.send_message(self.p, Channel.EMAIL, subject=" ", body="본문")
        self.assertEqual(Message.objects.get().status, Message.Status.FAILED)
        self.inf.email = ""
        self.inf.save()
        with self.assertRaisesMessage(ProviderError, "이메일이 없습니다"):
            services.send_message(self.p, Channel.EMAIL, subject="안내", body="본문")

    @override_settings(GMAIL_APP_PASSWORD="")
    def test_not_configured(self):
        with self.assertRaisesMessage(ProviderError, "GMAIL_APP_PASSWORD"):
            services.send_message(self.p, Channel.EMAIL, subject="안내", body="본문")

    def test_send_view(self):
        res = self.client.post(
            reverse("messaging:send", args=[self.p.pk]),
            {"channel": "email", "subject": "안내", "body": "안녕하세요"},
            follow=True,
        )
        self.assertContains(res, "발송 완료")
        self.assertContains(res, "안녕하세요")  # 메시지 이력에 표시
        self.assertEqual(len(mail.outbox), 1)


def ig_transport(calls, status=200, payload=None):
    def handler(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"username": "Cafe_Lover", "id": "IGSID1"})
        return httpx.Response(status, json=payload or {"recipient_id": "IGSID1", "message_id": "mid.api.1"})

    return httpx.MockTransport(handler)


@override_settings(**IG)
class InstagramSendTests(MessagingBase):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.provider = InstagramProvider(http=httpx.Client(transport=ig_transport(self.calls)))

    def test_requires_inbound_message_within_24h(self):
        with self.assertRaisesMessage(ProviderError, "첫 DM은 인스타 앱에서"):
            services.send_message(self.p, Channel.INSTAGRAM, body="안녕하세요", provider=self.provider)
        InstagramThread.objects.create(igsid="IGSID1", influencer=self.inf, last_inbound_at=timezone.now() - timedelta(hours=25))
        with self.assertRaisesMessage(ProviderError, "24시간이 지나"):
            services.send_message(self.p, Channel.INSTAGRAM, body="안녕하세요", provider=self.provider)
        self.assertEqual(self.calls, [])

    def test_send_within_window(self):
        InstagramThread.objects.create(igsid="IGSID1", influencer=self.inf, last_inbound_at=timezone.now() - timedelta(hours=1))
        msg = services.send_message(self.p, Channel.INSTAGRAM, body="설문 링크 드려요", provider=self.provider, user=self.user)
        self.assertEqual(msg.external_id, "mid.api.1")
        request = self.calls[0]
        self.assertEqual(str(request.url), "https://graph.instagram.com/v23.0/me/messages")
        self.assertEqual(request.headers["Authorization"], "Bearer tok")
        self.assertEqual(json.loads(request.content), {"recipient": {"id": "IGSID1"}, "message": {"text": "설문 링크 드려요"}})

    def test_api_error_is_logged(self):
        InstagramThread.objects.create(igsid="IGSID1", influencer=self.inf, last_inbound_at=timezone.now())
        provider = InstagramProvider(http=httpx.Client(transport=ig_transport([], status=400, payload={"error": {"message": "Invalid token"}})))
        with self.assertRaisesMessage(ProviderError, "Invalid token"):
            services.send_message(self.p, Channel.INSTAGRAM, body="hi", provider=provider)
        self.assertEqual(Message.objects.get().status, Message.Status.FAILED)

    def test_too_long(self):
        InstagramThread.objects.create(igsid="IGSID1", influencer=self.inf, last_inbound_at=timezone.now())
        with self.assertRaisesMessage(ProviderError, "1000자"):
            services.send_message(self.p, Channel.INSTAGRAM, body="가" * 1001, provider=self.provider)


@override_settings(**IG)
class InstagramWebhookTests(MessagingBase):
    def payload(self, *, mid="mid.in.1", echo=False, text="네 참여할게요!"):
        sender, recipient = ("OURIG", "IGSID1") if echo else ("IGSID1", "OURIG")
        message = {"mid": mid, "text": text}
        if echo:
            message["is_echo"] = True
        return {"object": "instagram", "entry": [{"id": "OURIG", "time": 1, "messaging": [
            {"sender": {"id": sender}, "recipient": {"id": recipient}, "timestamp": int(timezone.now().timestamp() * 1000), "message": message}
        ]}]}

    def post(self, payload, secret="s3cret"):
        body = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(reverse("messaging:webhook", args=["instagram"]), body, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=sig)

    def test_verify_challenge(self):
        url = reverse("messaging:webhook", args=["instagram"])
        res = self.client.get(url, {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
        self.assertEqual(res.content, b"42")
        res = self.client.get(url, {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"})
        self.assertEqual(res.status_code, 403)

    def test_bad_signature_rejected(self):
        self.assertEqual(self.post(self.payload(), secret="wrong").status_code, 403)
        self.assertFalse(Message.objects.exists())

    def test_inbound_creates_thread_matches_influencer_and_dedupes(self):
        with mock.patch.object(InstagramProvider, "fetch_username", return_value="Cafe_Lover"):
            self.assertEqual(self.post(self.payload()).status_code, 200)
            self.post(self.payload())  # Meta 재전송
        thread = InstagramThread.objects.get()
        self.assertEqual((thread.igsid, thread.username, thread.influencer), ("IGSID1", "cafe_lover", self.inf))
        self.assertIsNotNone(thread.last_inbound_at)
        msg = Message.objects.get()
        self.assertEqual((msg.direction, msg.status, msg.influencer, msg.body), ("in", "received", self.inf, "네 참여할게요!"))
        # 이제 24시간 창이 열려 발송 가능
        self.assertIsNone(InstagramProvider().unavailable_reason(self.p))

    def test_echo_of_manual_dm_is_logged_without_opening_window(self):
        with mock.patch.object(InstagramProvider, "fetch_username", return_value="cafe_lover"):
            self.post(self.payload(mid="mid.echo.1", echo=True, text="안녕하세요 협찬 제안드려요"))
        msg = Message.objects.get()
        self.assertEqual((msg.direction, msg.influencer), ("out", self.inf))
        self.assertIsNone(InstagramThread.objects.get().last_inbound_at)

    def test_unmatched_thread_linked_in_admin_backfills_messages(self):
        with mock.patch.object(InstagramProvider, "fetch_username", return_value=""):
            self.post(self.payload())
        thread = InstagramThread.objects.get()
        self.assertIsNone(thread.influencer)
        services.link_thread(thread, self.inf)
        self.assertEqual(Message.objects.get().influencer, self.inf)

    def test_unknown_provider_404(self):
        self.assertEqual(self.client.get("/hooks/kakao/").status_code, 404)


class DetailPanelTests(MessagingBase):
    def test_detail_shows_compose_and_template_render(self):
        tpl = MessageTemplate.objects.create(name="설문 안내", channel="", subject="[{{캠페인}}] 설문", body="{{이름}}님 {{설문링크}}")
        res = self.client.get(reverse("campaigns:participation", args=[self.p.pk]))
        self.assertContains(res, "메시지 보내기")
        self.assertContains(res, "설문 링크 (이 인플루언서 전용)")
        res = self.client.get(reverse("messaging:compose", args=[self.p.pk]), {"channel": "email", "template": tpl.pk})
        self.assertContains(res, "[12월 시딩] 설문")
        self.assertContains(res, "카페러버님 https://docs.google.com/forms/d/e/R/viewform?usp=pp_url")
        self.assertNotContains(res, "<html")


@override_settings(**GMAIL)
class ShippingCampaignMessagingTests(MessagingBase):
    def test_send_updates_last_contact_but_no_survey_stage_for_shipping(self):
        from campaigns.models import CampaignKind

        self.campaign.kind = CampaignKind.SHIPPING
        self.campaign.save()
        body = services.render_template("Please fill in {{설문링크}}", self.p)
        services.send_message(self.p, Channel.EMAIL, subject="hi", body=body, user=self.user)
        self.p.refresh_from_db()
        self.assertEqual(self.p.stage, Stage.CONTACT_TARGET)  # 배송형에는 '설문 발송' 단계가 없다
        self.assertEqual(self.p.last_contacted_at, timezone.localdate())
