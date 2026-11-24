from django import forms

from campaigns.forms import DateInput

from .models import ContentPost


class ContentPostForm(forms.ModelForm):
    class Meta:
        model = ContentPost
        fields = [
            "url",
            "posted_at",
            "format",
            "views_d7",
            "likes_d7",
            "comments_d7",
            "saves_d7",
            "shares_d7",
            "views_d30",
            "likes_d30",
            "comments_d30",
            "saves_d30",
            "shares_d30",
            "discount_code_uses",
            "link_clicks",
            "revenue",
            "notes",
        ]
        widgets = {"posted_at": DateInput()}
