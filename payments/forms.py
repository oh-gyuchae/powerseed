from django import forms

from campaigns.forms import DateInput

from .models import Payment


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = [
            "installment",
            "amount",
            "currency",
            "fx_rate",
            "method",
            "fee",
            "tax_document",
            "tax_document_received",
            "invoice_received",
            "paid_at",
            "notes",
        ]
        widgets = {"paid_at": DateInput()}
