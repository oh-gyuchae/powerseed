from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from campaigns.models import Campaign, CampaignKind, Participation
from core.utils import parse_id
from payments.services import CostBook
from sheets.columns import SCOPE_CLIENT, client_only, display_screen
from sheets.exports import export_response

from . import selectors
from .columns import POST_COLUMNS
from .forms import ContentPostForm


@login_required
def content_list(request):
    """시트 ③ 콘텐츠 성과. 계산 열(참여율·CPV·CPM·ROAS)은 매번 계산한다."""
    campaign_id = parse_id(request.GET.get("campaign"))
    book = CostBook()
    rows = selectors.with_metrics(selectors.posts(campaign_id), book)
    download = request.GET.get("download")
    if download in ("xlsx", "csv"):
        columns = client_only(POST_COLUMNS) if request.GET.get("scope") == SCOPE_CLIENT else POST_COLUMNS
        return export_response(
            rows, columns, download, filename=f"콘텐츠성과_{timezone.localdate():%Y%m%d}", title="콘텐츠 성과"
        )
    return render(
        request,
        "performance/content_list.html",
        {
            "columns": POST_COLUMNS,
            "rows": [{"obj": o, "cells": [display_screen(c.get(o)) for c in POST_COLUMNS]} for o in rows],
            "campaigns": Campaign.objects.order_by("-created_at"),
            "campaign_id": campaign_id,
            "query": request.GET.urlencode(),
            "missing_rates": sorted(book.missing_rates),
        },
    )


@login_required
@require_POST
def post_add(request, pk):
    participation = get_object_or_404(Participation, pk=pk)
    form = ContentPostForm(request.POST)
    if form.is_valid():
        post = form.save(commit=False)
        post.participation = participation
        post.save()
        messages.success(request, "게시물 성과를 추가했습니다.")
    else:
        for field, errors in form.errors.items():
            label = form.fields[field].label if field in form.fields else ""
            messages.error(request, f"게시물 추가 실패 — {label}: {' '.join(errors)}")
    return redirect(reverse("campaigns:participation", args=[pk]) + "#posts")


@login_required
def report(request):
    """시트 ⑤ 대시보드: 국가별 퍼널, 캠페인별 비용·성과, 성과 좋은 인플루언서 TOP 10."""
    kind = request.GET.get("kind") if request.GET.get("kind") in CampaignKind.values else None
    order = request.GET.get("top") if request.GET.get("top") in selectors.TOP_ORDERS else "cpv"
    campaigns, missing_rates = selectors.campaign_performance(kind)
    return render(
        request,
        "performance/report.html",
        {
            "kind": kind,
            "kinds": CampaignKind.choices,
            "order": order,
            "orders": selectors.TOP_ORDERS.items(),
            "funnel": selectors.country_funnel(kind),
            "campaigns": campaigns,
            "top": selectors.top_influencers(order, kind=kind),
            "missing_rates": sorted(missing_rates),
        },
    )
