import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core.choices import Country, Currency
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


class Category(models.TextChoices):
    SKINCARE = "skincare", "스킨케어"
    MAKEUP = "makeup", "메이크업"
    HAIR = "hair", "헤어"
    BODY = "body", "바디"
    FRAGRANCE = "fragrance", "향수"
    NAIL = "nail", "네일"
    FASHION = "fashion", "패션"
    FOOD = "food", "푸드"
    LIFESTYLE = "lifestyle", "라이프스타일"
    OTHER = "other", "기타"


class AudienceGender(models.TextChoices):
    FEMALE = "female", "여성 위주"
    MALE = "male", "남성 위주"
    MIXED = "mixed", "비슷함"


def next_code(country: str) -> str:
    """국가별 일련번호 ID: 'US' -> 'US-001', 'US-002', ..."""
    prefix = f"{country}-"
    numbers = [
        int(code[len(prefix) :])
        for code in Influencer.objects.filter(code__startswith=prefix).values_list("code", flat=True)
        if code[len(prefix) :].isdigit()
    ]
    return f"{prefix}{max(numbers, default=0) + 1:03d}"


class Influencer(TimeStampedModel):
    """계정 마스터 — 캠페인과 무관한 인플루언서 고유 정보 (시트 ① 인플루언서 DB)."""

    class Source(models.TextChoices):
        COLLECTOR = "collector", "해시태그 수집기"
        MANUAL = "manual", "수동 등록"
        SURVEY = "survey", "설문"

    class ReelsAvgSource(models.TextChoices):
        AUTO = "auto", "자동 산출"
        SURVEY = "survey", "본인 기입"
        MANUAL = "manual", "수동 입력"

    code = models.CharField(
        "인플루언서 ID",
        max_length=12,
        blank=True,
        editable=False,
        help_text="국가를 입력하면 'US-001' 형식으로 자동 부여됩니다. 한 번 부여되면 바뀌지 않습니다.",
    )
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

    engagement_rate = models.DecimalField(
        "참여율(%)", max_digits=5, decimal_places=2, null=True, blank=True, help_text="예: 3.25"
    )

    country = models.CharField("국가", max_length=2, choices=Country.choices, blank=True)
    timezone = models.CharField("시간대", max_length=40, blank=True, help_text="예: America/Los_Angeles, Asia/Tokyo")
    languages = models.CharField("사용 언어", max_length=100, blank=True, help_text="예: 영어, 스페인어")
    category = models.CharField("카테고리", max_length=15, choices=Category.choices, blank=True)
    audience_country = models.CharField(
        "주요 오디언스 국가", max_length=2, choices=Country.choices, blank=True
    )
    audience_gender = models.CharField("오디언스 성별", max_length=10, choices=AudienceGender.choices, blank=True)
    audience_age = models.CharField("오디언스 연령", max_length=30, blank=True, help_text="예: 18-24")

    contact = models.CharField("연락처", max_length=200, blank=True, help_text="이메일 외 연락처 (WhatsApp, LINE 등)")
    agency = models.CharField("에이전시", max_length=100, blank=True, help_text="소속이 없으면 비워 둡니다.")
    desired_rate = models.DecimalField("희망 단가", max_digits=12, decimal_places=2, null=True, blank=True)
    desired_rate_currency = models.CharField(
        "희망 단가 통화", max_length=3, choices=Currency.choices, default=Currency.KRW
    )
    is_blacklisted = models.BooleanField(
        "블랙리스트", default=False, help_text="체크하면 캠페인에 새로 추가할 수 없습니다. 사유는 비고에 적습니다."
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
        constraints = [
            models.UniqueConstraint(fields=["code"], condition=~Q(code=""), name="uniq_influencer_code"),
        ]

    def __str__(self):
        return f"@{self.instagram_handle}"

    @property
    def has_agency(self):
        return bool(self.agency)

    def save(self, *args, **kwargs):
        self.instagram_handle = normalize_handle(self.instagram_handle)
        if not self.account_url and self.platform == Platform.INSTAGRAM and self.instagram_handle:
            self.account_url = f"https://www.instagram.com/{self.instagram_handle}/"
        if not self.code and self.country:
            self.code = next_code(self.country)
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = {*kwargs["update_fields"], "code"}
        super().save(*args, **kwargs)
