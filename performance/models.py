"""시트 ③ 콘텐츠 성과 — 업로드된 게시물 1개 = ContentPost 1행.

조회수·반응은 7일차 / 30일차를 따로 기록한다. 계산 열(참여율·CPV·CPM·ROAS)은 저장하지 않고
`performance.selectors`에서 비용과 함께 계산한다.
"""

from django.db import models

from core.models import TimeStampedModel

METRICS = ("views", "likes", "comments", "saves", "shares")


class ContentPost(TimeStampedModel):
    class Format(models.TextChoices):
        REELS = "reels", "릴스"
        FEED = "feed", "피드"
        STORY = "story", "스토리"
        SHORTS = "shorts", "쇼츠"
        VIDEO = "video", "영상(틱톡·유튜브)"

    participation = models.ForeignKey(
        "campaigns.Participation", verbose_name="참여 인플루언서", on_delete=models.CASCADE, related_name="posts"
    )
    url = models.URLField("게시물 URL")
    posted_at = models.DateField("업로드일", null=True, blank=True)
    format = models.CharField("형식", max_length=10, choices=Format.choices, default=Format.REELS)

    views_d7 = models.PositiveIntegerField("조회수(7일)", null=True, blank=True)
    likes_d7 = models.PositiveIntegerField("좋아요(7일)", null=True, blank=True)
    comments_d7 = models.PositiveIntegerField("댓글(7일)", null=True, blank=True)
    saves_d7 = models.PositiveIntegerField("저장(7일)", null=True, blank=True)
    shares_d7 = models.PositiveIntegerField("공유(7일)", null=True, blank=True)

    views_d30 = models.PositiveIntegerField("조회수(30일)", null=True, blank=True)
    likes_d30 = models.PositiveIntegerField("좋아요(30일)", null=True, blank=True)
    comments_d30 = models.PositiveIntegerField("댓글(30일)", null=True, blank=True)
    saves_d30 = models.PositiveIntegerField("저장(30일)", null=True, blank=True)
    shares_d30 = models.PositiveIntegerField("공유(30일)", null=True, blank=True)

    discount_code_uses = models.PositiveIntegerField("할인코드 사용 수", null=True, blank=True)
    link_clicks = models.PositiveIntegerField("링크 클릭(UTM)", null=True, blank=True)
    revenue = models.PositiveBigIntegerField("매출(원)", null=True, blank=True)
    notes = models.CharField("메모", max_length=300, blank=True)

    class Meta:
        verbose_name = "콘텐츠 성과"
        verbose_name_plural = "콘텐츠 성과"
        ordering = ["-posted_at", "-created_at"]

    def __str__(self):
        return f"{self.participation} / {self.get_format_display()}"

    @property
    def checkpoint(self):
        """성과 계산에 쓰는 기록 시점: 30일차 조회수가 있으면 30일차, 없으면 7일차."""
        return "d30" if self.views_d30 is not None else "d7"

    def metric(self, name):
        return getattr(self, f"{name}_{self.checkpoint}")

    @property
    def views(self):
        return self.metric("views")

    @property
    def engagement_rate(self):
        """(좋아요+댓글+저장+공유) ÷ 조회수 × 100, 소수 둘째 자리."""
        views = self.views
        if not views:
            return None
        reactions = sum(self.metric(name) or 0 for name in METRICS[1:])
        return round(reactions / views * 100, 2)
