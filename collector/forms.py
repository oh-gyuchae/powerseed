from django import forms
from django.conf import settings

from .services import normalize_hashtag


class HashtagJobForm(forms.Form):
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
