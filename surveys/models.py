from django.db import models

from core.models import TimeStampedModel


class Target(models.TextChoices):
    """구글 폼 문항 하나가 플랫폼의 어느 칸으로 옮겨 적히는지."""

    EXTRA = "extra", "추가 답변 (시트 열로 표시)"
    IGNORE = "ignore", "가져오지 않음"
    PARTICIPATION_CODE = "participation_code", "참여 코드 (링크에 자동 입력, 응답자 확인용)"
    INSTAGRAM_HANDLE = "instagram_handle", "인스타 계정 (응답자 확인용)"
    ACCOUNT_NAME = "account_name", "계정 이름"
    EMAIL = "email", "이메일"
    FOLLOWER_COUNT = "follower_count", "팔로워 수"
    MONTHLY_REELS_AVG = "monthly_reels_avg", "한 달 릴스 평균 (본인 기입)"
    PARTICIPATION_STATUS = "participation_status", "참여 의사"
    AVAILABLE_VISIT_DATES = "available_visit_dates", "방문 가능일"
    FEE_REQUESTED = "fee_requested", "희망 원고료"
    PAYOUT_METHOD = "payout_method", "송금 수단"
    SPECIAL_NOTES = "special_notes", "특이사항"


# 한 폼에서 문항 하나에만 지정할 수 있는 대상 (추가 답변/가져오지 않음 제외 전부)
UNIQUE_TARGETS = {t for t in Target.values if t not in (Target.EXTRA, Target.IGNORE)}


class CampaignForm(TimeStampedModel):
    """캠페인에 연결된 구글 폼. 문항 추가·수정은 구글 폼에서 하고, 플랫폼은 불러와서 옮겨 적는다."""

    campaign = models.OneToOneField(
        "campaigns.Campaign", verbose_name="캠페인", on_delete=models.CASCADE, related_name="google_form"
    )
    form_id = models.CharField("구글 폼 ID", max_length=200)
    title = models.CharField("폼 제목", max_length=300, blank=True)
    responder_uri = models.URLField("응답 링크", max_length=500, blank=True)
    synced_at = models.DateTimeField("마지막 동기화", null=True, blank=True)
    last_error = models.TextField("마지막 오류", blank=True)

    class Meta:
        verbose_name = "구글 폼"
        verbose_name_plural = "구글 폼"

    def __str__(self):
        return self.title or self.form_id

    @property
    def edit_url(self):
        return f"https://docs.google.com/forms/d/{self.form_id}/edit"


class FormQuestion(models.Model):
    form = models.ForeignKey(CampaignForm, on_delete=models.CASCADE, related_name="questions")
    question_id = models.CharField("질문 ID", max_length=100)
    title = models.CharField("질문", max_length=500)
    kind = models.CharField("유형", max_length=20, blank=True)
    options = models.JSONField("선택지", default=list, blank=True)
    position = models.PositiveIntegerField("순서", default=0)
    target = models.CharField("옮겨 적을 칸", max_length=30, choices=Target.choices, default=Target.EXTRA)
    include_in_client_export = models.BooleanField("고객사 파일에 포함", default=True)
    is_active = models.BooleanField("폼에 있음", default=True, help_text="구글 폼에서 삭제된 문항은 False")

    class Meta:
        verbose_name = "구글 폼 문항"
        verbose_name_plural = "구글 폼 문항"
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["form", "question_id"], name="uniq_form_question")]

    def __str__(self):
        return self.title


class FormResponse(TimeStampedModel):
    class MatchMethod(models.TextChoices):
        CODE = "code", "참여 코드"
        HANDLE = "handle", "인스타 계정"
        MANUAL = "manual", "수동 연결"

    form = models.ForeignKey(CampaignForm, on_delete=models.CASCADE, related_name="responses")
    response_id = models.CharField("응답 ID", max_length=200)
    participation = models.ForeignKey(
        "campaigns.Participation",
        verbose_name="참여 인플루언서",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="form_responses",
    )
    match_method = models.CharField("연결 방법", max_length=10, choices=MatchMethod.choices, blank=True)
    answers = models.JSONField("답변 원본", default=dict, help_text="{질문 ID: [답변, ...]}")
    respondent_handle = models.CharField("응답자 인스타 계정", max_length=100, blank=True)
    submitted_at = models.DateTimeField("제출 일시")
    applied_at = models.DateTimeField("플랫폼 반영 일시", null=True, blank=True)

    class Meta:
        verbose_name = "구글 폼 응답"
        verbose_name_plural = "구글 폼 응답"
        ordering = ["-submitted_at"]
        constraints = [models.UniqueConstraint(fields=["form", "response_id"], name="uniq_form_response")]

    def __str__(self):
        return f"{self.form} / {self.respondent_handle or self.response_id}"
