from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.http import content_disposition_header

from campaigns import selectors, services
from campaigns.models import Campaign, Participation, Stage
from core.utils import parse_id

from .columns import SCOPE_CLIENT, SCOPE_INTERNAL, campaign_columns, columns_for, display_screen
from .exports import to_csv, to_xlsx
from .forms import SheetRowForm


def _filters(params):
    return {
        "assignee_id": parse_id(params.get("assignee")),
        "stage": params.get("stage") if params.get("stage") in Stage.values else None,
        "exclude_closed": params.get("exclude_closed") == "1",
    }


def _cells(p, columns, form=None):
    cells = []
    for col in columns:
        cell = {"col": col, "value": display_screen(col.get(p))}
        if form is not None and col.field:
            cell["field"] = form[col.field]
        cells.append(cell)
    return cells


def _row(request, p, form=None, error=None):
    return render(
        request,
        "sheets/_row_form.html" if form is not None else "sheets/_row.html",
        {"p": p, "cells": _cells(p, campaign_columns(p.campaign), form), "form": form, "error": error},
    )


@login_required
def campaign_sheet(request, pk):
    campaign = get_object_or_404(Campaign.objects.select_related("client"), pk=pk)
    filters = _filters(request.GET)
    columns = campaign_columns(campaign)
    rows = [{"p": p, "cells": _cells(p, columns)} for p in selectors.sheet_participations(campaign, **filters)]
    return render(
        request,
        "sheets/sheet.html",
        {
            "campaign": campaign,
            "columns": columns,
            "rows": rows,
            "filters": filters,
            "query": request.GET.urlencode(),
            "stage_choices": Stage.choices,
            "users": get_user_model().objects.filter(is_active=True).order_by("username"),
        },
    )


@login_required
def sheet_row(request, pk):
    """GET: 보기 행 / GET ?edit=1: 수정 행 / POST: 저장 후 보기 행 (HTMX 부분 갱신)."""
    p = get_object_or_404(Participation.objects.select_related("campaign", "influencer", "assignee"), pk=pk)
    if request.method == "GET":
        return _row(request, p, SheetRowForm(instance=p) if request.GET.get("edit") == "1" else None)

    form = SheetRowForm(request.POST, instance=p)
    if not form.is_valid():
        return _row(request, p, form)
    try:
        with transaction.atomic():
            new_stage = form.cleaned_data["stage"]
            if new_stage != p.stage:
                services.change_stage(p, new_stage, user=request.user, memo="시트에서 변경")
            form.save()
    except ValidationError as e:
        p.refresh_from_db()
        return _row(request, p, form, error=f"{e.messages[0]} 재오픈은 참여 상세 화면에서 하세요.")
    return _row(request, p)


@login_required
def campaign_export(request, pk, fmt):
    campaign = get_object_or_404(Campaign.objects.select_related("client"), pk=pk)
    scope = SCOPE_INTERNAL if request.GET.get("scope") == SCOPE_INTERNAL else SCOPE_CLIENT
    columns = columns_for(scope, campaign)
    participations = selectors.sheet_participations(campaign, **_filters(request.GET))

    suffix = "사내용" if scope == SCOPE_INTERNAL else "고객사"
    filename = f"{campaign.name}_{suffix}_{timezone.localdate():%Y%m%d}.{fmt}"
    if fmt == "xlsx":
        body = to_xlsx(participations, columns, title=campaign.name)
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        body = to_csv(participations, columns)
        content_type = "text/csv; charset=utf-8"
    return HttpResponse(
        body,
        content_type=content_type,
        headers={"Content-Disposition": content_disposition_header(True, filename)},
    )
