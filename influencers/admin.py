from django.contrib import admin

from .models import Influencer


@admin.register(Influencer)
class InfluencerAdmin(admin.ModelAdmin):
    list_display = (
        "instagram_handle",
        "code",
        "account_name",
        "platform",
        "country",
        "category",
        "follower_count",
        "monthly_reels_avg",
        "is_blacklisted",
        "owner",
        "created_at",
    )
    list_filter = ("platform", "country", "category", "is_blacklisted", "source", "owner")
    search_fields = ("instagram_handle", "code", "account_name", "email", "notes", "special_notes")
    readonly_fields = ("code", "reels_avg_updated_at", "reels_avg_sample_size", "created_at", "updated_at")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "code",
                    "account_name",
                    "platform",
                    "instagram_handle",
                    "account_url",
                    "follower_count",
                    "engagement_rate",
                    "category",
                )
            },
        ),
        ("지역·언어", {"fields": ("country", "timezone", "languages")}),
        ("오디언스", {"fields": ("audience_country", "audience_gender", "audience_age")}),
        ("연락·계약", {"fields": ("email", "contact", "agency", "desired_rate", "desired_rate_currency")}),
        (
            "한 달 릴스 평균",
            {"fields": ("monthly_reels_avg", "reels_avg_source", "reels_avg_sample_size", "reels_avg_updated_at")},
        ),
        ("메모", {"fields": ("is_blacklisted", "notes", "special_notes")}),
        ("관리", {"fields": ("source", "discovered_hashtags", "owner", "created_at", "updated_at")}),
    )
