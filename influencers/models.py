import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import TimeStampedModel


# 인스타 사용자명 규칙: 영문 소문자·숫자·마침표·밑줄, 최대 30자
HANDLE_RE = re.compile(r"^[a-z0-9._]{1,30}$")
# instagram.com/<여기>/ 자리에 오지만 계정이 아닌 경로 (게시물·릴스·탐색 등)
_NON_PROFILE_PATHS = {"p", "reel", "reels", "tv", "explore", "accounts", "direct", "about", "developer", "legal"}


def normalize_handle(value: str) -> str:
    """'@Foo.Bar', 'https://instagram.com/foo.bar/' -> 'foo.bar'.

    URLs that don't point at a profile (posts, reels, ...) yield '' — the handle can't be known.
    Story URLs (instagram.com/stories/<handle>/...) yield the story owner's handle.
    """
    value = (value or "").strip()
    match = re.search(r"instagram\.com/([^?#]*)", value, re.IGNORECASE)
    if match:
        segments = [s for s in match.group(1).split("/") if s]
        if segments and segments[0].lower() == "stories":
            segments = segments[1:]
        if not segments or segments[0].lower() in _NON_PROFILE_PATHS:
            return ""
        value = segments[0]
    return value.lstrip("@").strip("/").lower()


def is_valid_handle(handle: str) -> bool:
    return bool(HANDLE_RE.fullmatch(handle or ""))


def validate_handle(value):
    if not is_valid_handle(normalize_handle(value)):
        raise ValidationError(
            "인스타 계정 형식이 아닙니다. 영문·숫자·마침표·밑줄 30자 이내의 계정명 또는 프로필 URL을 입력하세요."
        )


class Platform(models.TextChoices):
    INSTAGRAM = "instagram", "인스타그램"
    YOUTUBE = "youtube", "유튜브"
    TIKTOK = "tiktok", "틱톡"
    BLOG = "blog", "블로그"
    OTHER = "other", "기타"


class Influencer(TimeStampedModel):
    """계정 마스터 — 캠페인과 무관한 인플루언서 고유 정보."""

    class Source(models.TextChoices):
        COLLECTOR = "collector", "해시태그 수집기"
        MANUAL = "manual", "수동 등록"
        SURVEY = "survey", "설문"

    class ReelsAvgSource(models.TextChoices):
        AUTO = "auto", "자동 산출"
        SURVEY = "survey", "본인 기입"
        MANUAL = "manual", "수동 입력"

    account_name = models.CharField("계정 이름", max_length=100, blank=True)
    platform = models.CharField("플랫폼", max_length=20, choices=Platform.choices, default=Platform.INSTAGRAM)
    instagram_handle = models.CharField(
        "인스타 계정",
        max_length=100,
        unique=True,
        validators=[validate_handle],
        help_text="@ 없이 소문자로 저장됩니다.",
    )
    account_url = models.URLField("계정 URL", blank=True)
    email = models.EmailField("이메일", blank=True, help_text="Gmail 발송 대상 (설문 응답으로도 채워짐)")
    follower_count = models.PositiveIntegerField("팔로워 수", null=True, blank=True)

    monthly_reels_avg = models.PositiveIntegerField("한 달 릴스 평균 조회수", null=True, blank=True)
    reels_avg_sample_size = models.PositiveSmallIntegerField("릴스 평균 표본 수", null=True, blank=True)
    reels_avg_updated_at = models.DateTimeField("릴스 평균 갱신일", null=True, blank=True)
    reels_avg_source = models.CharField(
        "릴스 평균 출처", max_length=10, choices=ReelsAvgSource.choices, blank=True
    )

    notes = models.TextField("비고", blank=True)
    special_notes = models.TextField("특이사항", blank=True)
    source = models.CharField("등록 경로", max_length=10, choices=Source.choices, default=Source.MANUAL)
    discovered_hashtags = models.JSONField("발견 해시태그", default=list, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="담당자",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_influencers",
    )

    class Meta:
        verbose_name = "인플루언서"
        verbose_name_plural = "인플루언서"
        ordering = ["-created_at"]

    def __str__(self):
        return f"@{self.instagram_handle}"

    def save(self, *args, **kwargs):
        self.instagram_handle = normalize_handle(self.instagram_handle)
        if not self.account_url and self.platform == Platform.INSTAGRAM and self.instagram_handle:
            self.account_url = f"https://www.instagram.com/{self.instagram_handle}/"
        super().save(*args, **kwargs)
