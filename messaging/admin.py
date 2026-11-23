from django.contrib import admin

from . import services
from .models import InstagramThread, Message, MessageTemplate


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "channel", "subject", "updated_at")
    list_filter = ("channel",)
    fieldsets = (
        (
            None,
            {
                "fields": ("name", "channel", "subject", "body"),
                "description": "본문 변수: {{이름}} {{계정}} {{캠페인}} {{방문장소}} {{설문링크}}",
            },
        ),
    )


@admin.register(InstagramThread)
class InstagramThreadAdmin(admin.ModelAdmin):
    list_display = ("__str__", "influencer", "last_inbound_at")
    list_filter = (("influencer", admin.EmptyFieldListFilter),)
    search_fields = ("username", "igsid", "influencer__instagram_handle")
    readonly_fields = ("igsid", "last_inbound_at", "created_at", "updated_at")
    autocomplete_fields = ("influencer",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.influencer_id:
            services.link_thread(obj, obj.influencer)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "channel", "direction", "status", "recipient", "influencer", "sent_by")
    list_filter = ("channel", "direction", "status")
    search_fields = ("recipient", "body", "influencer__instagram_handle")
    readonly_fields = [f.name for f in Message._meta.fields]

    def has_add_permission(self, request):
        return False
