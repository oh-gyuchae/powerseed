from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from campaigns.models import Campaign, Participation
from core.utils import parse_id
from sheets.columns import display_screen
from sheets.exports import export_response

from .columns import PAYMENT_COLUMNS
from .forms import PaymentForm
from .models import ExchangeRate, Payment
from .services import CostBook


def _cost_summary(campaign_id):
    """참여 건별 총비용(원) — 비용이 하나라도 있는 건만."""
    qs = Participation.objects.select_related("campaign", "influencer").prefetch_related("payments")
    if campaign_id:
        qs = qs.filter(campaign_id=campaign_id)
    qs = qs.filter(
        Q(payments__isnull=False) | Q(product_cost__isnull=False) | Q(shipping_cost__isnull=False) | Q(fee_amount__isnull=False)
    ).distinct()
    book = CostBook()
    rows = []
    for p in qs.order_by("campaign_id", "pk"):
        total = book.participation_cost(p)
        if not total:
            continue
        payments = list(p.payments.all())
        rows.append(
            {
                "p": p,
                "payments": sum(x.cost_krw or 0 for x in payments) if payments else None,
                "product_cost": p.product_cost,
                "shipping_cost": p.shipping_cost,
                "total": total,
                # 지급 내역 없이 확정 원고료로 계산한 예상 비용
                "estimated": not payments and p.fee_amount is not None and p.is_committed,
            }
        )
    return rows, book.missing_rates


def _latest_rates():
    latest = {}
    for rate in ExchangeRate.objects.order_by("currency", "-effective_date"):
        latest.setdefault(rate.currency, rate)
    return list(latest.values())


@login_required
def payment_list(request):
    """시트 ④ 정산: 지급 내역 + 참여 건별 총비용(원화)."""
    campaign_id = parse_id(request.GET.get("campaign"))
    status = request.GET.get("status") if request.GET.get("status") in ("paid", "unpaid") else ""
    qs = Payment.objects.select_related("participation__campaign", "participation__influencer")
    if campaign_id:
        qs = qs.filter(participation__campaign_id=campaign_id)
    if status == "paid":
        qs = qs.filter(paid_at__isnull=False)
    elif status == "unpaid":
        qs = qs.filter(paid_at__isnull=True)

    download = request.GET.get("download")
    if download in ("xlsx", "csv"):
        return export_response(qs, PAYMENT_COLUMNS, download, filename=f"정산_{timezone.localdate():%Y%m%d}", title="정산")

    summary, missing_rates = _cost_summary(campaign_id)
    missing_rates |= {p.currency for p in qs if p.amount_krw is None}
    return render(
        request,
        "payments/list.html",
        {
            "columns": PAYMENT_COLUMNS,
            "rows": [{"obj": o, "cells": [display_screen(c.get(o)) for c in PAYMENT_COLUMNS]} for o in qs],
            "summary": summary,
            "summary_total": sum(r["total"] for r in summary),
            "campaigns": Campaign.objects.order_by("-created_at"),
            "campaign_id": campaign_id,
            "status": status,
            "query": request.GET.urlencode(),
            "missing_rates": sorted(missing_rates),
            "rates": _latest_rates(),
        },
    )


@login_required
@require_POST
def payment_add(request, pk):
    participation = get_object_or_404(Participation, pk=pk)
    form = PaymentForm(request.POST)
    if form.is_valid():
        payment = form.save(commit=False)
        payment.participation = participation
        payment.save()
        if payment.amount_krw is None:
            messages.error(request, f"{payment.currency} 환율이 환율표에 없어 원화 환산액을 계산하지 못했습니다.")
        else:
            messages.success(request, f"지급 내역을 추가했습니다 (원화 {payment.amount_krw:,}원).")
    else:
        for field, errors in form.errors.items():
            label = form.fields[field].label if field in form.fields else ""
            messages.error(request, f"지급 내역 추가 실패 — {label}: {' '.join(errors)}")
    return redirect(reverse("campaigns:participation", args=[pk]) + "#payments")
