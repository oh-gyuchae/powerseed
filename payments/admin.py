from django.contrib import admin

from .models import ExchangeRate, Payment


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ("currency", "rate", "effective_date", "notes")
    list_filter = ("currency",)
    date_hierarchy = "effective_date"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "participation",
        "installment",
        "amount",
        "currency",
        "fx_rate",
        "amount_krw",
        "method",
        "invoice_received",
        "paid_at",
    )
    list_filter = ("installment", "currency", "method", "tax_document", "invoice_received", "participation__campaign")
    search_fields = ("participation__influencer__instagram_handle", "participation__influencer__code")
    autocomplete_fields = ("participation",)
    readonly_fields = ("amount_krw", "fee_krw", "created_at", "updated_at")


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ("installment", "amount", "currency", "fx_rate", "amount_krw", "method", "paid_at")
    readonly_fields = ("amount_krw",)
