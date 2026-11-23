from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class HashtagJob(TimeStampedModel):
    """해시태그 1개에 대한 수집 작업."""

    class Status(models.TextChoices):
        PENDING = "pending", "대기"
        RUNNING = "running", "수집 중"
        DONE = "done", "완료"
        FAILED = "failed", "실패"

    hashtag = models.CharField("해시태그", max_length=100, db_index=True)
    limit = models.PositiveIntegerField("최대 수집 수", default=200)
    status = models.CharField("상태", max_length=10, choices=Status.choices, default=Status.PENDING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="요청자",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hashtag_jobs",
    )
    result_count = models.PositiveIntegerField("후보 수", default=0)
    skipped_count = models.PositiveIntegerField("제외 수", default=0, help_text="계정 형식 오류·중복")
    error = models.TextField("오류", blank=True)
    started_at = models.DateTimeField("시작 일시", null=True, blank=True)
    finished_at = models.DateTimeField("종료 일시", null=True, blank=True)

    class Meta:
        verbose_name = "해시태그 수집 작업"
        verbose_name_plural = "해시태그 수집 작업"
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.hashtag} ({self.get_status_display()})"


class Candidate(TimeStampedModel):
    """수집된 계정. 운영자가 검토해 승인하면 인플루언서·참여 건이 된다."""

    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "검토 대기"
        APPROVED = "approved", "승인"
        REJECTED = "rejected", "제외"

    job = models.ForeignKey(HashtagJob, verbose_name="수집 작업", on_delete=models.CASCADE, related_name="candidates")
    handle = models.CharField("인스타 계정", max_length=30, db_index=True)
    account_name = models.CharField("계정 이름", max_length=100, blank=True)
    account_url = models.URLField("계정 URL", blank=True)
    follower_count = models.PositiveIntegerField("팔로워 수", null=True, blank=True)
    raw = models.JSONField("원본 데이터", default=dict, blank=True)
    review_status = models.CharField(
        "검토 상태", max_length=10, choices=ReviewStatus.choices, default=ReviewStatus.PENDING, db_index=True
    )
    influencer = models.ForeignKey(
        "influencers.Influencer",
        verbose_name="연결된 인플루언서",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="candidates",
    )

    class Meta:
        verbose_name = "수집 후보"
        verbose_name_plural = "수집 후보"
        ordering = ["-follower_count", "handle"]
        constraints = [
            models.UniqueConstraint(fields=["job", "handle"], name="uniq_job_handle"),
        ]

    def __str__(self):
        return f"@{self.handle}"
