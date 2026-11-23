from django.contrib import admin

from .models import Candidate, HashtagJob


@admin.register(HashtagJob)
class HashtagJobAdmin(admin.ModelAdmin):
    list_display = ("hashtag", "status", "result_count", "skipped_count", "requested_by", "created_at")
    list_filter = ("status",)
    search_fields = ("hashtag",)
    readonly_fields = ("result_count", "skipped_count", "error", "started_at", "finished_at")


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ("handle", "job", "follower_count", "review_status", "influencer")
    list_filter = ("review_status",)
    search_fields = ("handle", "account_name")
    raw_id_fields = ("job", "influencer")
