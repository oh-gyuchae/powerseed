from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.core.exceptions import ValidationError

from . import services
from .models import Campaign, Client, Participation, Stage, StatusLog


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "contact", "created_at")
    search_fields = ("name",)


INLINE_ADD_FIELDS = ("participation_status", "fee_amount", "payout_status", "assignee")


class ParticipationInline(admin.TabularInline):
    model = Participation
    extra = 0
    fields = ("influencer", "stage", *INLINE_ADD_FIELDS)
    readonly_fields = ("stage",)
    autocomplete_fields = ("influencer",)
    show_change_link = True


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "client", "status", "start_date", "end_date", "manager")
    list_filter = ("status", "client", "manager")
    search_fields = ("name", "client__name")
    inlines = [ParticipationInline]

    def save_formset(self, request, form, formset, change):
        if formset.model is not Participation:
            return super().save_formset(request, form, formset, change)
        # New rows go through add_to_campaign() so they get the initial StatusLog and default fee.
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for obj in instances:
            if obj.pk is None:
                entered = {f: getattr(obj, f) for f in INLINE_ADD_FIELDS}
                services.add_to_campaign(
                    obj.influencer,
                    form.instance,
                    user=request.user,
                    defaults={k: v for k, v in entered.items() if v is not None},
                )
            else:
                obj.save()
        formset.save_m2m()


class StatusLogInline(admin.TabularInline):
    model = StatusLog
    extra = 0
    can_delete = False
    fields = ("created_at", "from_stage", "to_stage", "changed_by", "memo")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class ChangeStageForm(ActionForm):
    to_stage = forms.ChoiceField(label="변경할 단계", choices=Stage.choices, required=False)


@admin.register(Participation)
class ParticipationAdmin(admin.ModelAdmin):
    list_display = (
        "influencer",
        "campaign",
        "stage",
        "participation_status",
        "fee_amount",
        "payout_method",
        "payout_status",
        "confirmed_visit_at",
        "assignee",
    )
    list_filter = ("stage", "payout_status", "participation_status", "campaign", "assignee")
    search_fields = ("influencer__instagram_handle", "influencer__account_name", "campaign__name")
    autocomplete_fields = ("influencer",)
    readonly_fields = (
        "stage",
        "survey_token",
        "survey_submitted_at",
        "created_at",
        "updated_at",
    )
    inlines = [StatusLogInline]
    action_form = ChangeStageForm
    actions = ["change_stage_action"]

    @admin.action(description="선택 항목 단계 변경")
    def change_stage_action(self, request, queryset):
        to_stage = request.POST.get("to_stage")
        if not to_stage:
            self.message_user(request, "변경할 단계를 선택하세요.", messages.WARNING)
            return
        ok, failed = 0, []
        for participation in queryset:
            try:
                services.change_stage(participation, to_stage, user=request.user, memo="admin 일괄 변경")
                ok += 1
            except ValidationError as e:
                failed.append(f"{participation.influencer}: {e.messages[0]}")
        self.message_user(request, f"{ok}건 변경 완료")
        for msg in failed:
            self.message_user(request, msg, messages.ERROR)

    def save_model(self, request, obj, form, change):
        is_new = obj.pk is None
        if is_new and obj.fee_amount is None:
            obj.fee_amount = obj.campaign.default_fee  # same default as services.add_to_campaign()
        super().save_model(request, obj, form, change)
        if is_new:
            StatusLog.objects.create(participation=obj, to_stage=obj.stage, changed_by=request.user)


@admin.register(StatusLog)
class StatusLogAdmin(admin.ModelAdmin):
    list_display = ("participation", "from_stage", "to_stage", "changed_by", "created_at")
    list_filter = ("to_stage",)
    readonly_fields = ("participation", "from_stage", "to_stage", "changed_by", "memo", "created_at")
