from django.contrib import admin

from .models import Influencer


@admin.register(Influencer)
class InfluencerAdmin(admin.ModelAdmin):
    list_display = (
        "instagram_handle",
        "account_name",
        "platform",
        "follower_count",
        "monthly_reels_avg",
        "source",
        "owner",
        "created_at",
    )
    list_filter = ("platform", "source", "owner")
    search_fields = ("instagram_handle", "account_name", "email", "notes", "special_notes")
    readonly_fields = ("reels_avg_updated_at", "reels_avg_sample_size", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("account_name", "platform", "instagram_handle", "account_url", "email", "follower_count")}),
        (
            "한 달 릴스 평균",
            {"fields": ("monthly_reels_avg", "reels_avg_source", "reels_avg_sample_size", "reels_avg_updated_at")},
        ),
        ("메모", {"fields": ("notes", "special_notes")}),
        ("관리", {"fields": ("source", "discovered_hashtags", "owner", "created_at", "updated_at")}),
    )
