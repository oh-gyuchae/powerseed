from django import forms

from campaigns.forms import ParticipationForm
from campaigns.models import Stage


class SheetRowForm(ParticipationForm):
    """시트 한 행 인라인 수정. 단계(stage)는 모델 필드로 저장하지 않고 change_stage()로 넘긴다.

    시트에 열이 있는 필드만 남긴다 — 열이 없는 필드는 전송되지 않으므로 남겨 두면 빈 값으로 덮어쓴다.
    """

    stage = forms.ChoiceField(label="진행 단계", choices=Stage.choices)

    def __init__(self, *args, columns, **kwargs):
        super().__init__(*args, **kwargs)
        editable = {c.field for c in columns if c.field}
        for name in list(self.fields):
            if name not in editable:
                del self.fields[name]
        self.fields["stage"].choices = self.instance.campaign.stage_choices
        if self.instance.pk and not self.is_bound:
            self.initial["stage"] = self.instance.stage
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "w-full min-w-24 border rounded px-1 py-0.5 text-xs bg-white")
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs["rows"] = 2
