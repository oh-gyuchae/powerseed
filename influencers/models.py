import re

from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


def normalize_handle(value: str) -> str:
    """'@Foo.Bar', 'https://instagram.com/foo.bar/' -> 'foo.bar'."""
    value = (value or "").strip()
    match = re.search(r"instagram\.com/([^/?#]+)", value, re.IGNORECASE)
    if match:
        value = match.group(1)
    return value.lstrip("@").strip("/").lower()


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
        "인스타 계정", max_length=100, unique=True, help_text="@ 없이 소문자로 저장됩니다."
    )
    account_url = models.URLField("계정 URL", blank=True)
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
