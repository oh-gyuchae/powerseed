import datetime

from django import forms

from .models import CampaignKind, Participation


class DateListField(forms.CharField):
    """Comma/newline separated YYYY-MM-DD values <-> list[str]."""

    def prepare_value(self, value):
        if isinstance(value, list):
            return ", ".join(value)
        return value

    def to_python(self, value):
        raw = super().to_python(value) or ""
        dates = []
        for part in raw.replace("\n", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                dates.append(datetime.date.fromisoformat(part).isoformat())
            except ValueError:
                raise forms.ValidationError(f"날짜 형식이 올바르지 않습니다: {part} (예: 2026-12-01)")
        return sorted(set(dates))


class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%dT%H:%M", **kwargs)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


VISIT_ONLY_FIELDS = {"available_visit_dates", "confirmed_visit_at"}
SHIPPING_ONLY_FIELDS = {
    "fee_currency",
    "collab_type",
    "deliverables",
    "carrier",
    "tracking_number",
    "shipped_at",
    "customs_issue",
    "received_at",
    "draft_submitted_at",
    "revision_count",
    "usage_rights_until",
    "ad_usage_allowed",
    "ad_code",
    "disclosure_checked",
    "last_contacted_at",
    "next_action",
}


class ParticipationForm(forms.ModelForm):
    """참여 건 수정. 캠페인 유형(방문형/배송형)에 없는 필드는 폼에서 뺀다 (보이지 않는 값을 지우지 않도록)."""

    available_visit_dates = DateListField(
        label="방문 가능일", required=False, help_text="쉼표로 구분 (예: 2026-12-01, 2026-12-03)"
    )

    class Meta:
        model = Participation
        fields = [
            "assignee",
            "participation_status",
            "collab_type",
            "deliverables",
            "available_visit_dates",
            "confirmed_visit_at",
            "fee_requested",
            "fee_amount",
            "fee_currency",
            "payout_method",
            "carrier",
            "tracking_number",
            "shipped_at",
            "customs_issue",
            "received_at",
            "draft_submitted_at",
            "revision_count",
            "upload_due_at",
            "upload_url",
            "usage_rights_until",
            "ad_usage_allowed",
            "ad_code",
            "disclosure_checked",
            "product_cost",
            "shipping_cost",
            "last_contacted_at",
            "next_action",
            "notes",
            "special_notes",
        ]
        widgets = {
            "confirmed_visit_at": DateTimeLocalInput(),
            "upload_due_at": DateTimeLocalInput(),
            "shipped_at": DateInput(),
            "received_at": DateInput(),
            "draft_submitted_at": DateInput(),
            "usage_rights_until": DateInput(),
            "last_contacted_at": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "special_notes": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {"upload_due_at": "업로드 기한(예정일)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hidden = SHIPPING_ONLY_FIELDS if self.instance.campaign.kind == CampaignKind.VISIT else VISIT_ONLY_FIELDS
        for name in hidden:
            self.fields.pop(name, None)


class AddInfluencerForm(forms.Form):
    handles = forms.CharField(
        label="인스타 계정",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "@handle 또는 프로필 URL, 줄바꿈/쉼표로 여러 개"}),
    )

    def clean_handles(self):
        from influencers.models import is_valid_handle, normalize_handle

        raw = self.cleaned_data["handles"].replace(",", "\n")
        entries = [e.strip() for e in raw.splitlines() if e.strip()]
        invalid = [e for e in entries if not is_valid_handle(normalize_handle(e))]
        if invalid:
            raise forms.ValidationError(
                "인스타 계정으로 인식할 수 없는 항목이 있습니다 (게시물·릴스 링크는 불가, 프로필 URL 또는 계정명): "
                + ", ".join(invalid[:10])
                + (f" 외 {len(invalid) - 10}개" if len(invalid) > 10 else "")
            )
        handles = list(dict.fromkeys(normalize_handle(e) for e in entries))
        if not handles:
            raise forms.ValidationError("계정을 하나 이상 입력하세요.")
        return handles
