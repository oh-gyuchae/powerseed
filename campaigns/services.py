"""Business logic for the seeding pipeline.

All stage changes must go through `change_stage` so that every transition is
logged (StatusLog) and stage-dependent fields stay consistent.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import CLOSED_STAGES, Participation, Stage, StatusLog


@transaction.atomic
def change_stage(participation: Participation, to_stage: str, *, user=None, memo: str = "", force=False):
    """Move a participation to `to_stage`, logging the change.

    Closed participations (paid / declined / dropped) can only be reopened with
    `force=True`, so a finished payout is never silently undone.
    """
    to_stage = Stage(to_stage)
    from_stage = participation.stage
    if from_stage == to_stage:
        return participation
    if from_stage in CLOSED_STAGES and not force:
        raise ValidationError(f"종료된 건({Stage(from_stage).label})은 force=True 로만 변경할 수 있습니다.")

    now = timezone.now()
    participation.stage = to_stage
    update_fields = ["stage", "updated_at"]

    if to_stage == Stage.DECLINED:
        participation.participation_status = Participation.ParticipationStatus.NO
        update_fields.append("participation_status")
    elif to_stage == Stage.CONFIRMED:
        participation.participation_status = Participation.ParticipationStatus.YES
        update_fields.append("participation_status")
    elif to_stage == Stage.UPLOADED and not participation.uploaded_at:
        participation.uploaded_at = now
        update_fields.append("uploaded_at")
    elif to_stage == Stage.PAYOUT_PENDING:
        participation.payout_status = Participation.PayoutStatus.PENDING
        update_fields.append("payout_status")
    elif to_stage == Stage.PAID:
        participation.payout_status = Participation.PayoutStatus.PAID
        participation.paid_at = participation.paid_at or now
        update_fields += ["payout_status", "paid_at"]

    participation.save(update_fields=update_fields)
    StatusLog.objects.create(
        participation=participation, from_stage=from_stage, to_stage=to_stage, changed_by=user, memo=memo
    )
    return participation


@transaction.atomic
def add_to_campaign(influencer, campaign, *, user=None) -> tuple[Participation, bool]:
    """Register an influencer as a contact target for a campaign (idempotent)."""
    participation, created = Participation.objects.get_or_create(
        campaign=campaign,
        influencer=influencer,
        defaults={"assignee": user, "fee_amount": campaign.default_fee},
    )
    if created:
        StatusLog.objects.create(
            participation=participation, from_stage="", to_stage=Stage.CONTACT_TARGET, changed_by=user
        )
    return participation, created
