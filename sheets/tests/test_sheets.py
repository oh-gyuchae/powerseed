import csv
import io
from datetime import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from campaigns import services
from campaigns.models import Campaign, Client, Stage, StatusLog
from influencers.models import Influencer
from sheets.columns import COLUMNS, SCOPE_CLIENT, columns_for


class SheetBase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ops", password="pw-12345")
        self.client.force_login(self.user)
        self.campaign = Campaign.objects.create(
            client=Client.objects.create(name="고객사A"), name="11월 시딩", status=Campaign.Status.ACTIVE
        )
        self.inf = Influencer.objects.create(instagram_handle="seed_one", account_name="씨드", follower_count=12000)
        self.p, _ = services.add_to_campaign(self.inf, self.campaign, user=self.user)
        self.p.fee_amount = 150000
        self.p.notes = "사내 메모"
        self.p.special_notes = "=HYPERLINK(\"http://evil\")"
        self.p.confirmed_visit_at = timezone.make_aware(datetime(2026, 12, 1, 15, 30))
        self.p.save()
        dropped_inf = Influencer.objects.create(instagram_handle="gone_one")
        self.dropped, _ = services.add_to_campaign(dropped_inf, self.campaign, user=self.user)
        services.change_stage(self.dropped, Stage.DROPPED)


class ColumnTests(TestCase):
    def test_keys_unique_and_client_scope_drops_internal(self):
        keys = [c.key for c in COLUMNS]
        self.assertEqual(len(keys), len(set(keys)))
        client_keys = {c.key for c in columns_for(SCOPE_CLIENT)}
        self.assertNotIn("notes", client_keys)
        self.assertNotIn("assignee", client_keys)
        self.assertIn("fee_amount", client_keys)

    def test_editable_columns_exist_on_form(self):
        from sheets.forms import SheetRowForm

        form_fields = set(SheetRowForm.base_fields)
        for col in COLUMNS:
            if col.field:
                self.assertIn(col.field, form_fields, col.key)


class SheetPageTests(SheetBase):
    def test_sheet_renders_rows_and_filters(self):
        url = reverse("sheets:sheet", args=[self.campaign.pk])
        res = self.client.get(url)
        self.assertContains(res, "@seed_one")
        self.assertContains(res, "150,000")
        self.assertContains(res, "@gone_one")
        res = self.client.get(url, {"exclude_closed": "1", "assignee": "abc", "stage": "bogus"})
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "@gone_one")

    def test_requires_login(self):
        self.client.logout()
        res = self.client.get(reverse("sheets:sheet", args=[self.campaign.pk]))
        self.assertEqual(res.status_code, 302)


class RowEditTests(SheetBase):
    def _post(self, **overrides):
        data = {
            "stage": self.p.stage,
            "participation_status": self.p.participation_status,
            "available_visit_dates": "",
            "fee_amount": "200000",
        }
        data.update(overrides)
        return self.client.post(reverse("sheets:row", args=[self.p.pk]), data, HTTP_HX_REQUEST="true")

    def test_edit_form_partial(self):
        res = self.client.get(reverse("sheets:row", args=[self.p.pk]), {"edit": "1"})
        self.assertContains(res, 'name="fee_amount"')
        self.assertNotContains(res, "<html")

    def test_save_fields_and_stage_goes_through_change_stage(self):
        res = self._post(stage=Stage.CONTACTED)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "200,000")
        self.p.refresh_from_db()
        self.assertEqual(self.p.fee_amount, 200000)
        self.assertEqual(self.p.stage, Stage.CONTACTED)
        log = StatusLog.objects.filter(participation=self.p).first()
        self.assertEqual((log.to_stage, log.changed_by, log.memo), (Stage.CONTACTED, self.user, "시트에서 변경"))

    def test_closed_row_stage_change_rejected_without_saving(self):
        self.p = self.dropped
        res = self._post(stage=Stage.CONTACTED, fee_amount="999")
        self.assertContains(res, "재오픈은 참여 상세 화면에서")
        self.dropped.refresh_from_db()
        self.assertEqual(self.dropped.stage, Stage.DROPPED)
        self.assertNotEqual(self.dropped.fee_amount, 999)

    def test_invalid_input_shows_errors(self):
        res = self._post(available_visit_dates="내일")
        self.assertContains(res, "날짜 형식이 올바르지 않습니다")
        self.p.refresh_from_db()
        self.assertEqual(self.p.fee_amount, 150000)


class ExportTests(SheetBase):
    def _export(self, fmt, **params):
        return self.client.get(reverse("sheets:export", args=[self.campaign.pk, fmt]), params)

    def test_client_csv(self):
        res = self._export("csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertTrue(res.content.startswith(b"\xef\xbb\xbf"))  # BOM for Excel
        rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
        header = rows[0]
        self.assertIn("원고료", header)
        self.assertNotIn("비고", header)
        self.assertNotIn("담당자", header)
        row = dict(zip(header, rows[1]))
        self.assertEqual(row["인스타 계정"], "seed_one")
        self.assertEqual(row["확정 방문 일시"], "2026-12-01 15:30")
        self.assertTrue(row["특이사항"].startswith("'="))  # formula injection guarded
        self.assertEqual(len(rows), 3)

    def test_internal_xlsx_respects_filters(self):
        res = self._export("xlsx", scope="internal", exclude_closed="1")
        self.assertEqual(res.status_code, 200)
        ws = load_workbook(io.BytesIO(res.content)).active
        header = [c.value for c in ws[1]]
        self.assertIn("비고", header)
        self.assertEqual(ws.max_row, 2)  # header + seed_one (dropped excluded)
        row = dict(zip(header, [c.value for c in ws[2]]))
        self.assertEqual(row["원고료"], 150000)
        self.assertEqual(row["확정 방문 일시"], datetime(2026, 12, 1, 15, 30))
        self.assertEqual(row["비고"], "사내 메모")
        special = ws.cell(row=2, column=header.index("특이사항") + 1)
        self.assertEqual(special.data_type, "s")  # stored as text, not a formula

    def test_unknown_format_404(self):
        res = self.client.get(f"/campaigns/{self.campaign.pk}/export.pdf")
        self.assertEqual(res.status_code, 404)
