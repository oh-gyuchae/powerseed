from django.contrib import admin

from .models import ContentPost


@admin.register(ContentPost)
class ContentPostAdmin(admin.ModelAdmin):
    list_display = ("participation", "format", "posted_at", "views_d7", "views_d30", "revenue")
    list_filter = ("format", "participation__campaign")
    search_fields = ("participation__influencer__instagram_handle", "participation__influencer__code", "url")
    autocomplete_fields = ("participation",)
    fieldsets = (
        (None, {"fields": ("participation", "url", "posted_at", "format")}),
        ("7일차", {"fields": ("views_d7", "likes_d7", "comments_d7", "saves_d7", "shares_d7")}),
        ("30일차", {"fields": ("views_d30", "likes_d30", "comments_d30", "saves_d30", "shares_d30")}),
        ("전환", {"fields": ("discount_code_uses", "link_clicks", "revenue")}),
        ("메모", {"fields": ("notes",)}),
    )


class ContentPostInline(admin.TabularInline):
    model = ContentPost
    extra = 0
    fields = ("url", "format", "posted_at", "views_d7", "views_d30", "revenue")
    show_change_link = True
