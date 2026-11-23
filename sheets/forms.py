from django import forms

from campaigns.forms import ParticipationForm
from campaigns.models import Stage


class SheetRowForm(ParticipationForm):
    """시트 한 행 인라인 수정. 단계(stage)는 모델 필드로 저장하지 않고 change_stage()로 넘긴다."""

    stage = forms.ChoiceField(label="진행 단계", choices=Stage.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            self.initial["stage"] = self.instance.stage
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "w-full min-w-24 border rounded px-1 py-0.5 text-xs bg-white")
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs["rows"] = 2
