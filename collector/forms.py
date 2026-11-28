from django import forms
from django.conf import settings

from influencers.models import Category

from .selectors import open_campaigns
from .services import normalize_hashtag


class _TargetFields(forms.Form):
    category = forms.ChoiceField(label="카테고리", choices=[("", "자동 추정"), *Category.choices], required=False)
    campaign = forms.ModelChoiceField(label="대상 캠페인", queryset=None, required=False, empty_label="나중에 선택")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["campaign"].queryset = open_campaigns()


class HashtagJobForm(_TargetFields):
    hashtag = forms.CharField(label="해시태그", max_length=101)
    limit = forms.IntegerField(label="최대 수집 수", min_value=1)

    def clean_hashtag(self):
        hashtag = normalize_hashtag(self.cleaned_data["hashtag"])
        if not hashtag:
            raise forms.ValidationError("해시태그는 공백 없이 글자·숫자·밑줄로 입력하세요.")
        return hashtag

    def clean_limit(self):
        limit = self.cleaned_data["limit"]
        if limit > settings.COLLECTOR_MAX_LIMIT:
            raise forms.ValidationError(f"최대 수집 수는 {settings.COLLECTOR_MAX_LIMIT}개까지입니다.")
        return limit


class ResultUploadForm(_TargetFields):
    file = forms.FileField(label="insta-finder 결과 파일", help_text="result.xlsx 또는 결과 CSV")
