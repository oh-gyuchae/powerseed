"""Read-side queries for the board and the manager dashboard."""

from datetime import timedelta

from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.utils import timezone

from .models import CLOSED_STAGES, PIPELINE, Campaign, Participation, Stage, StatusLog

# 설문 발송 후 이 기간 동안 응답이 없으면 "미응답"으로 표시
SURVEY_NO_RESPONSE_DAYS = 3

_BEFORE_VISIT = [Stage.CONFIRMED, Stage.VISIT_SCHEDULED]
_BEFORE_UPLOAD = [Stage.CONFIRMED, Stage.VISIT_SCHEDULED, Stage.VISITED]


def board_columns(participations):
    """Group participations into pipeline columns + a closed (declined/dropped) column."""
    by_stage = {stage: [] for stage in PIPELINE}
    closed = []
    for p in participations:
        if p.stage in (Stage.DECLINED, Stage.DROPPED):
            closed.append(p)
        else:
            by_stage[Stage(p.stage)].append(p)
    columns = [{"stage": stage, "items": items} for stage, items in by_stage.items()]
    return columns, closed


def campaign_summaries():
    """Active/planning campaigns with per-stage counts for the dashboard."""
    stage_counts = {
        f"n_{stage.value}": Count("participations", filter=Q(participations__stage=stage)) for stage in Stage
    }
    campaigns = (
        Campaign.objects.exclude(status__in=[Campaign.Status.DONE, Campaign.Status.CANCELED])
        .select_related("client", "manager")
        .annotate(total=Count("participations"), **stage_counts)
    )
    rows = []
    for c in campaigns:
        counts = [{"stage": s, "count": getattr(c, f"n_{s.value}")} for s in PIPELINE]
        closed = sum(getattr(c, f"n_{s.value}") for s in CLOSED_STAGES)
        rows.append(
            {
                "campaign": c,
                "counts": counts,
                "open": c.total - closed,
                "confirmed": sum(
                    x["count"] for x in counts if PIPELINE.index(x["stage"]) >= PIPELINE.index(Stage.CONFIRMED)
                ),
            }
        )
    return rows


def _last_entered(stage):
    """Subquery: when the participation last moved into `stage`."""
    return (
        StatusLog.objects.filter(participation=OuterRef("pk"), to_stage=stage)
        .values("participation")
        .annotate(at=Max("created_at"))
        .values("at")
    )


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
        "upload_overdue": qs.filter(stage__in=_BEFORE_UPLOAD, upload_due_at__lt=now).order_by("upload_due_at"),
        "survey_no_response": qs.filter(stage=Stage.SURVEY_SENT)
        .annotate(survey_sent_at=Subquery(_last_entered(Stage.SURVEY_SENT)))
        .filter(survey_sent_at__lt=now - timedelta(days=SURVEY_NO_RESPONSE_DAYS))
        .order_by("survey_sent_at"),
        "payout_waiting": qs.filter(stage__in=[Stage.UPLOADED, Stage.PAYOUT_PENDING]).order_by("uploaded_at"),
    }
