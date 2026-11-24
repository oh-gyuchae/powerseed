"""Read-side queries for the board and the manager dashboard."""

from datetime import timedelta

from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.utils import timezone

from .models import (
    CLOSED_STAGES,
    CONTRACT_STAGE,
    DROPPED_OUT_STAGES,
    PIPELINES,
    WAITING_UPLOAD_STAGES,
    Campaign,
    CampaignKind,
    Participation,
    Stage,
    StatusLog,
)

# 설문 발송 후 이 기간 동안 응답이 없으면 "미응답"으로 표시
SURVEY_NO_RESPONSE_DAYS = 3

_BEFORE_VISIT = [Stage.CONFIRMED, Stage.VISIT_SCHEDULED]


def board_columns(campaign, participations):
    """Group participations into the campaign kind's pipeline columns + a closed (declined/dropped/...) column."""
    by_stage = {stage: [] for stage in campaign.pipeline}
    closed = []
    for p in participations:
        if p.stage in by_stage:
            by_stage[p.stage].append(p)
        else:
            closed.append(p)
    columns = [{"stage": stage, "items": items} for stage, items in by_stage.items()]
    return columns, closed


def campaign_summaries():
    """Active/planning campaigns with per-stage counts for the dashboard, grouped by campaign kind."""
    stage_counts = {
        f"n_{stage.value}": Count("participations", filter=Q(participations__stage=stage)) for stage in Stage
    }
    campaigns = (
        Campaign.objects.exclude(status__in=[Campaign.Status.DONE, Campaign.Status.CANCELED])
        .select_related("client", "manager")
        .annotate(total=Count("participations"), **stage_counts)
    )
    groups = {kind: {"kind": kind, "stages": PIPELINES[kind], "rows": []} for kind in CampaignKind}
    for c in campaigns:
        pipeline = PIPELINES[c.kind]
        contract_at = pipeline.index(CONTRACT_STAGE[c.kind])
        counts = [{"stage": s, "count": getattr(c, f"n_{s.value}")} for s in pipeline]
        closed = sum(getattr(c, f"n_{s.value}") for s in CLOSED_STAGES)
        groups[c.kind]["rows"].append(
            {
                "campaign": c,
                "counts": counts,
                "open": c.total - closed,
                "confirmed": sum(x["count"] for i, x in enumerate(counts) if i >= contract_at),
            }
        )
    return [g for g in groups.values() if g["rows"]]


def _last_entered(stage):
    """Subquery: when the participation last moved into `stage`."""
    return (
        StatusLog.objects.filter(participation=OuterRef("pk"), to_stage=stage)
        .values("participation")
        .annotate(at=Max("created_at"))
        .values("at")
    )


def upload_overdue(qs, now=None):
    """확정(계약) 후 업로드 기한이 지났는데 아직 올라오지 않은 건 — Participation.is_upload_overdue와 같은 기준."""
    now = now or timezone.now()
    return qs.filter(stage__in=WAITING_UPLOAD_STAGES, upload_due_at__lt=now, uploaded_at__isnull=True)


def dashboard_alerts(now=None, assignee=None):
    """Items needing a manager's attention."""
    now = now or timezone.now()
    qs = Participation.objects.select_related("campaign", "influencer", "assignee")
    if assignee is not None:
        qs = qs.filter(assignee=assignee)
    return {
        "visit_overdue": qs.filter(stage__in=_BEFORE_VISIT, confirmed_visit_at__lt=now).order_by(
            "confirmed_visit_at"
        ),
        "upload_overdue": upload_overdue(qs, now).order_by("upload_due_at"),
        "survey_no_response": qs.filter(stage=Stage.SURVEY_SENT)
        .annotate(survey_sent_at=Subquery(_last_entered(Stage.SURVEY_SENT)))
        .filter(survey_sent_at__lt=now - timedelta(days=SURVEY_NO_RESPONSE_DAYS))
        .order_by("survey_sent_at"),
        "payout_waiting": qs.filter(stage__in=[Stage.UPLOADED, Stage.PAYOUT_PENDING]).order_by("uploaded_at"),
    }


def sheet_participations(campaign, *, assignee_id=None, stage=None, exclude_closed=False, overdue=False):
    """Rows for the campaign sheet view / export, in registration order."""
    qs = campaign.participations.select_related("campaign", "influencer", "assignee").order_by("pk")
    if assignee_id:
        qs = qs.filter(assignee_id=assignee_id)
    if stage in Stage.values:
        qs = qs.filter(stage=stage)
    if exclude_closed:
        qs = qs.exclude(stage__in=DROPPED_OUT_STAGES)
    if overdue:
        qs = upload_overdue(qs)
    return qs
