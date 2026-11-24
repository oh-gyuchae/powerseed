from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from core.choices import Country
from sheets.columns import display_screen
from sheets.exports import export_response

from .columns import INFLUENCER_COLUMNS
from .models import Category, Influencer, Platform


def _filters(params):
    return {
        "q": params.get("q", "").strip(),
        "country": params.get("country") if params.get("country") in Country.values else "",
        "platform": params.get("platform") if params.get("platform") in Platform.values else "",
        "category": params.get("category") if params.get("category") in Category.values else "",
        "blacklist": params.get("blacklist") if params.get("blacklist") in ("only", "exclude") else "",
    }


def _queryset(filters):
    qs = Influencer.objects.select_related("owner").annotate(campaign_count=Count("participations"))
    if filters["q"]:
        q = filters["q"].lstrip("@")
        qs = qs.filter(
            Q(instagram_handle__icontains=q) | Q(account_name__icontains=q) | Q(code__iexact=q) | Q(email__icontains=q)
        )
    for name in ("country", "platform", "category"):
        if filters[name]:
            qs = qs.filter(**{name: filters[name]})
    if filters["blacklist"] == "only":
        qs = qs.filter(is_blacklisted=True)
    elif filters["blacklist"] == "exclude":
        qs = qs.filter(is_blacklisted=False)
    return qs.order_by("code", "instagram_handle")


@login_required
def influencer_list(request):
    """시트 ① 인플루언서 DB. 수정은 관리자 화면에서 한다."""
    filters = _filters(request.GET)
    qs = _queryset(filters)
    download = request.GET.get("download")
    if download in ("xlsx", "csv"):
        return export_response(
            qs, INFLUENCER_COLUMNS, download, filename=f"인플루언서DB_{timezone.localdate():%Y%m%d}", title="인플루언서 DB"
        )
    rows = [{"obj": o, "cells": [display_screen(c.get(o)) for c in INFLUENCER_COLUMNS]} for o in qs[:500]]
    return render(
        request,
        "influencers/list.html",
        {
            "columns": INFLUENCER_COLUMNS,
            "rows": rows,
            "total": qs.count(),
            "filters": filters,
            "query": request.GET.urlencode(),
            "countries": Country.choices,
            "platforms": Platform.choices,
            "categories": Category.choices,
        },
    )
