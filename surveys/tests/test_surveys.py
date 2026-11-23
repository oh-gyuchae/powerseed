import io
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from openpyxl import load_workbook

from campaigns import services as campaign_services
from campaigns.models import Campaign, Client, Participation, Stage
from influencers.models import Influencer
from surveys import parsing, services
from surveys.google_forms import GoogleFormsError, parse_form_id
from surveys.models import CampaignForm, FormResponse, Target

FORM_ID = "1FAIpQLSf_example_form_id_0123456789"
Q_CODE, Q_HANDLE, Q_NAME, Q_FEE, Q_DATES, Q_STATUS, Q_PAYOUT, Q_EXTRA = (
    "0a1b2c3d", "11aa22bb", "22bb33cc", "33cc44dd", "44dd55ee", "55ee66ff", "66ff7788", "77889900",
)


def form_payload(extra_items=()):
    def text(qid, title, paragraph=False):
        q = {"questionId": qid, "textQuestion": {"paragraph": paragraph}}
        return {"itemId": f"i{qid}", "title": title, "questionItem": {"question": q}}

    items = [
        text(Q_CODE, "참여 코드"),
        text(Q_HANDLE, "인스타그램 아이디"),
        text(Q_NAME, "성함(활동명)"),
        text(Q_FEE, "희망 원고료"),
        {"itemId": "i5", "title": "방문 가능한 날짜", "questionItem": {"question": {"questionId": Q_DATES, "choiceQuestion": {"type": "CHECKBOX", "options": [{"value": "12/1"}, {"value": "12/3"}]}}}},
        {"itemId": "i6", "title": "참여 여부", "questionItem": {"question": {"questionId": Q_STATUS, "choiceQuestion": {"type": "RADIO", "options": [{"value": "참여할게요"}, {"value": "어려워요"}]}}}},
        text(Q_PAYOUT, "정산 방법"),
        text(Q_EXTRA, "주차 필요 여부", paragraph=True),
        {"itemId": "i9", "title": "안내 문구", "textItem": {}},  # 질문이 아닌 항목은 무시
        *extra_items,
    ]
    return {
        "formId": FORM_ID,
        "info": {"title": "12월 카페 시딩 설문"},
        "responderUri": "https://docs.google.com/forms/d/e/RESP/viewform",
        "items": items,
    }


def response(rid, answers, submitted="2026-11-20T10:00:00Z"):
    return {
        "responseId": rid,
        "lastSubmittedTime": submitted,
        "answers": {qid: {"questionId": qid, "textAnswers": {"answers": [{"value": v} for v in vals]}} for qid, vals in answers.items()},
    }


class FakeFormsClient:
    def __init__(self, form, responses):
        self.form, self.responses = form, responses

    def get_form(self, form_id):
        return self.form

    def list_responses(self, form_id):
        return self.responses


class ParsingTests(SimpleTestCase):
    def test_amount(self):
        cases = {"10만원": 100000, "1.5만": 15000, "120,000원": 120000, "12k": 12000, "5천원": 5000, "협의": None}
        for text, expected in cases.items():
            self.assertEqual(parsing.parse_amount(text), expected, text)

    def test_dates(self):
        self.assertEqual(
            parsing.parse_dates(["2026-12-01", "12/3", "12월 5일, 12.7", "아무때나"], year=2026),
            ["2026-12-01", "2026-12-03", "2026-12-05", "2026-12-07"],
        )

    def test_participation_status(self):
        S = Participation.ParticipationStatus
        for text, expected in {"참여할게요": S.YES, "네": S.YES, "불참": S.NO, "참여 어려워요": S.NO, "고민 중": S.CONSIDERING, "": None}.items():
            self.assertEqual(parsing.parse_participation_status(text), expected, text)

    def test_payout(self):
        M = Participation.PayoutMethod
        self.assertEqual(parsing.parse_payout_method("계좌이체"), M.BANK_TRANSFER)
        self.assertEqual(parsing.parse_payout_method("사업자(세금계산서)"), M.TAX_INVOICE)
        self.assertEqual(parsing.parse_payout_method("문화상품권"), M.OTHER)

    def test_guess_target(self):
        cases = {
            "참여 코드": Target.PARTICIPATION_CODE,
            "인스타그램 아이디": Target.INSTAGRAM_HANDLE,
            "인스타 계정 이름": Target.ACCOUNT_NAME,
            "방문 참여 가능 날짜": Target.AVAILABLE_VISIT_DATES,
            "참여 여부": Target.PARTICIPATION_STATUS,
            "희망 원고료": Target.FEE_REQUESTED,
            "이메일 주소": Target.EMAIL,
            "주차 필요 여부": Target.EXTRA,
        }
        for title, expected in cases.items():
            self.assertEqual(parsing.guess_target(title), expected, title)

    def test_parse_form_id(self):
        self.assertEqual(parse_form_id(f"https://docs.google.com/forms/d/{FORM_ID}/edit#responses"), FORM_ID)
        with self.assertRaises(GoogleFormsError):
            parse_form_id("https://docs.google.com/forms/d/e/1FAIpQLSdxxxxxxxxxxxxxxxxxxxx/viewform")
        with self.assertRaises(GoogleFormsError):
            parse_form_id("https://forms.gle/abc")


class SurveyBase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ops", password="pw-12345")
        self.client.force_login(self.user)
        self.campaign = Campaign.objects.create(
            client=Client.objects.create(name="고객사A"), name="12월 시딩", start_date=date(2026, 12, 1)
        )
        self.inf = Influencer.objects.create(instagram_handle="cafe_lover")
        self.p, _ = campaign_services.add_to_campaign(self.inf, self.campaign, user=self.user)
        campaign_services.change_stage(self.p, Stage.CONTACTED)
        self.other = Influencer.objects.create(instagram_handle="by_handle")
        self.p2, _ = campaign_services.add_to_campaign(self.other, self.campaign, user=self.user)
        self.cf = services.connect_form(self.campaign, f"https://docs.google.com/forms/d/{FORM_ID}/edit")

    def sync(self, responses, form=None):
        return services.sync_form(self.cf, client=FakeFormsClient(form or form_payload(), responses))


class SyncTests(SurveyBase):
    def test_questions_imported_with_guessed_targets(self):
        result = self.sync([])
        self.assertEqual(result.questions, 8)
        targets = dict(self.cf.questions.values_list("question_id", "target"))
        self.assertEqual(targets[Q_CODE], Target.PARTICIPATION_CODE)
        self.assertEqual(targets[Q_HANDLE], Target.INSTAGRAM_HANDLE)
        self.assertEqual(targets[Q_EXTRA], Target.EXTRA)
        self.cf.refresh_from_db()
        self.assertEqual(self.cf.title, "12월 카페 시딩 설문")
        self.assertIsNotNone(self.cf.synced_at)

    def test_response_matched_by_code_is_transcribed(self):
        result = self.sync([
            response("r1", {
                Q_CODE: [str(self.p.survey_token)],
                Q_HANDLE: ["@someone_else"],
                Q_NAME: ["카페러버"],
                Q_FEE: ["15만원"],
                Q_DATES: ["12/1", "12/3"],
                Q_STATUS: ["참여할게요"],
                Q_PAYOUT: ["계좌이체"],
                Q_EXTRA: ["필요해요"],
            })
        ])
        self.assertEqual((result.new, result.unmatched), (1, 0))
        self.p.refresh_from_db()
        self.inf.refresh_from_db()
        self.assertEqual(self.p.fee_requested, 150000)
        self.assertEqual(self.p.available_visit_dates, ["2026-12-01", "2026-12-03"])
        self.assertEqual(self.p.participation_status, Participation.ParticipationStatus.YES)
        self.assertEqual(self.p.payout_method, Participation.PayoutMethod.BANK_TRANSFER)
        self.assertEqual(self.p.form_answers, {Q_EXTRA: "필요해요"})
        self.assertEqual(self.p.stage, Stage.RESPONDED)
        self.assertIsNotNone(self.p.survey_submitted_at)
        self.assertEqual(self.inf.account_name, "카페러버")
        self.assertEqual(self.inf.instagram_handle, "cafe_lover")  # 응답의 계정 답변으로 덮어쓰지 않음
        self.assertEqual(FormResponse.objects.get().match_method, FormResponse.MatchMethod.CODE)

    def test_match_by_handle_and_unmatched(self):
        self.sync([
            response("r1", {Q_HANDLE: ["https://instagram.com/By_Handle"]}),
            response("r2", {Q_HANDLE: ["stranger"]}),
        ])
        self.assertEqual(FormResponse.objects.get(response_id="r1").participation, self.p2)
        unmatched = FormResponse.objects.get(response_id="r2")
        self.assertIsNone(unmatched.participation)
        self.assertEqual(unmatched.respondent_handle, "stranger")

    def test_edited_response_is_reapplied_and_unchanged_skipped(self):
        self.sync([response("r1", {Q_CODE: [str(self.p.survey_token)], Q_FEE: ["10만"]})])
        result = self.sync([response("r1", {Q_CODE: [str(self.p.survey_token)], Q_FEE: ["10만"]})])
        self.assertEqual((result.new, result.updated), (0, 0))
        result = self.sync([response("r1", {Q_CODE: [str(self.p.survey_token)], Q_FEE: ["12만"]}, submitted="2026-11-21T09:00:00Z")])
        self.assertEqual(result.updated, 1)
        self.p.refresh_from_db()
        self.assertEqual(self.p.fee_requested, 120000)

    def test_questions_added_and_removed_in_google_form(self):
        self.sync([])
        new_item = {"itemId": "n", "title": "이메일", "questionItem": {"question": {"questionId": "aaaa0001", "textQuestion": {}}}}
        form = form_payload(extra_items=[new_item])
        form["items"] = [i for i in form["items"] if i.get("questionItem", {}).get("question", {}).get("questionId") != Q_EXTRA]
        self.sync([], form=form)
        self.assertFalse(self.cf.questions.get(question_id=Q_EXTRA).is_active)
        self.assertEqual(self.cf.questions.get(question_id="aaaa0001").target, Target.EMAIL)

    def test_api_error_is_recorded(self):
        class Broken:
            def get_form(self, form_id):
                raise GoogleFormsError("폼에 접근할 수 없습니다.")

        with self.assertRaises(GoogleFormsError):
            services.sync_form(self.cf, client=Broken())
        self.cf.refresh_from_db()
        self.assertIn("접근할 수 없습니다", self.cf.last_error)

    def test_closed_participation_keeps_stage_and_status(self):
        campaign_services.change_stage(self.p, Stage.DECLINED)
        self.sync([response("r1", {Q_CODE: [str(self.p.survey_token)], Q_STATUS: ["참여할게요"], Q_FEE: ["5만"]})])
        self.p.refresh_from_db()
        self.assertEqual(self.p.stage, Stage.DECLINED)
        self.assertEqual(self.p.participation_status, Participation.ParticipationStatus.NO)
        self.assertEqual(self.p.fee_requested, 50000)


class LinkAndPrefillTests(SurveyBase):
    def test_survey_link_prefills_code(self):
        self.sync([])
        link = services.survey_link(self.p)
        self.assertTrue(link.startswith("https://docs.google.com/forms/d/e/RESP/viewform?usp=pp_url&"))
        self.assertIn(f"entry.{int(Q_CODE, 16)}={self.p.survey_token}", link)

    def test_survey_link_without_code_question(self):
        self.sync([])
        self.cf.questions.filter(question_id=Q_CODE).update(target=Target.IGNORE)
        self.assertEqual(services.survey_link(self.p), "https://docs.google.com/forms/d/e/RESP/viewform")

    def test_no_form_no_link(self):
        self.cf.delete()
        self.assertEqual(services.survey_link(self.p), "")

    def test_manual_link_and_create(self):
        self.sync([response("r1", {Q_HANDLE: ["stranger"], Q_FEE: ["7만"]}), response("r2", {Q_NAME: ["무명"]})])
        r1 = FormResponse.objects.get(response_id="r1")
        url = reverse("surveys:link_response", args=[self.campaign.pk, r1.pk])
        self.client.post(url, {"action": "create"})
        r1.refresh_from_db()
        self.assertEqual(r1.participation.influencer.instagram_handle, "stranger")
        self.assertEqual(r1.participation.fee_requested, 70000)
        self.assertEqual(r1.participation.stage, Stage.RESPONDED)

        r2 = FormResponse.objects.get(response_id="r2")
        url = reverse("surveys:link_response", args=[self.campaign.pk, r2.pk])
        res = self.client.post(url, {"action": "create"}, follow=True)
        self.assertContains(res, "올바른 인스타 계정이 없어")
        self.client.post(url, {"participation": self.p2.pk})
        r2.refresh_from_db()
        self.assertEqual(r2.participation, self.p2)
        self.assertEqual(r2.match_method, FormResponse.MatchMethod.MANUAL)


class SettingsViewTests(SurveyBase):
    def test_settings_page(self):
        self.sync([response("r2", {Q_HANDLE: ["stranger"]})])
        res = self.client.get(reverse("surveys:settings", args=[self.campaign.pk]))
        self.assertContains(res, "12월 카페 시딩 설문")
        self.assertContains(res, "@stranger")
        self.assertContains(res, "주차 필요 여부")

    def test_connect_runs_sync_and_reports_error(self):
        self.cf.delete()
        with mock.patch("surveys.services.GoogleFormsClient.from_settings", side_effect=GoogleFormsError("서비스 계정 파일이 설정되지 않았습니다.")):
            res = self.client.post(
                reverse("surveys:connect", args=[self.campaign.pk]),
                {"form_url": f"https://docs.google.com/forms/d/{FORM_ID}/edit"},
                follow=True,
            )
        self.assertContains(res, "구글 폼을 연결했습니다")
        self.assertContains(res, "서비스 계정 파일이 설정되지 않았습니다")
        self.assertTrue(CampaignForm.objects.filter(campaign=self.campaign, form_id=FORM_ID).exists())

    def test_mapping_save_rejects_duplicates_and_reapplies(self):
        self.sync([response("r1", {Q_CODE: [str(self.p.survey_token)], Q_EXTRA: ["필요"]})])
        q_extra = self.cf.questions.get(question_id=Q_EXTRA)
        q_name = self.cf.questions.get(question_id=Q_NAME)
        url = reverse("surveys:questions", args=[self.campaign.pk])
        res = self.client.post(url, {f"target_{q_extra.pk}": Target.ACCOUNT_NAME}, follow=True)
        self.assertContains(res, "한 칸에는 문항 하나만")
        self.client.post(url, {f"target_{q_extra.pk}": Target.SPECIAL_NOTES, f"target_{q_name.pk}": Target.ACCOUNT_NAME, "reapply": "1"})
        self.p.refresh_from_db()
        self.assertEqual(self.p.special_notes, "필요")


class SheetIntegrationTests(SurveyBase):
    def test_extra_answers_become_sheet_columns(self):
        self.sync([response("r1", {Q_CODE: [str(self.p.survey_token)], Q_EXTRA: ["필요해요"]})])
        res = self.client.get(reverse("sheets:sheet", args=[self.campaign.pk]))
        self.assertContains(res, "주차 필요 여부")
        self.assertContains(res, "필요해요")

        res = self.client.get(reverse("sheets:export", args=[self.campaign.pk, "xlsx"]))
        ws = load_workbook(io.BytesIO(res.content)).active
        self.assertIn("주차 필요 여부", [c.value for c in ws[1]])

        self.cf.questions.filter(question_id=Q_EXTRA).update(include_in_client_export=False)
        res = self.client.get(reverse("sheets:export", args=[self.campaign.pk, "xlsx"]))
        ws = load_workbook(io.BytesIO(res.content)).active
        self.assertNotIn("주차 필요 여부", [c.value for c in ws[1]])
