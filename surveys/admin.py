from django.contrib import admin

from .models import CampaignForm, FormQuestion, FormResponse


class FormQuestionInline(admin.TabularInline):
    model = FormQuestion
    extra = 0
    fields = ("position", "title", "kind", "target", "include_in_client_export", "is_active")
    readonly_fields = ("position", "title", "kind", "is_active")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False  # 문항은 구글 폼에서 추가하고 '동기화'로 불러온다


@admin.register(CampaignForm)
class CampaignFormAdmin(admin.ModelAdmin):
    list_display = ("campaign", "title", "synced_at", "last_error")
    readonly_fields = ("title", "responder_uri", "synced_at", "last_error", "created_at", "updated_at")
    inlines = [FormQuestionInline]


@admin.register(FormResponse)
class FormResponseAdmin(admin.ModelAdmin):
    list_display = ("form", "respondent_handle", "participation", "match_method", "submitted_at", "applied_at")
    list_filter = ("form", "match_method")
    search_fields = ("respondent_handle", "response_id")
    readonly_fields = ("form", "response_id", "answers", "submitted_at", "applied_at", "match_method")
    raw_id_fields = ("participation",)
