"""Business logic for the seeding pipeline.

All stage changes must go through `change_stage` so that every transition is
logged (StatusLog) and stage-dependent fields stay consistent.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import CLOSED_STAGES, PIPELINE, Participation, Stage, StatusLog


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

    # 되돌리기(재오픈) 정책: 파이프라인 앞 단계로 돌아가면 그 이후에 기록된 사실을 지운다.
    # 거절/이탈로 가는 경우는 되돌리기가 아니므로 기록을 유지한다.
    if to_stage in PIPELINE:
        position = PIPELINE.index(to_stage)
        if position < PIPELINE.index(Stage.PAID) and participation.paid_at:
            participation.paid_at = None
            update_fields.append("paid_at")
        if position < PIPELINE.index(Stage.PAYOUT_PENDING) and (
            participation.payout_status != Participation.PayoutStatus.UNPAID
        ):
            participation.payout_status = Participation.PayoutStatus.UNPAID
            update_fields.append("payout_status")
        if position < PIPELINE.index(Stage.UPLOADED) and participation.uploaded_at:
            participation.uploaded_at = None
            update_fields.append("uploaded_at")
    if from_stage == Stage.DECLINED:
        participation.participation_status = Participation.ParticipationStatus.NO_RESPONSE
        update_fields.append("participation_status")

    # 도착 단계에 맞춰 연관 필드 동기화 (재오픈 초기화보다 우선)
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
def add_to_campaign(influencer, campaign, *, user=None, defaults=None) -> tuple[Participation, bool]:
    """Register an influencer as a contact target for a campaign (idempotent).

    `defaults` overrides initial field values, and is only applied when a new row is created.
    """
    initial = {"assignee": user, "fee_amount": campaign.default_fee}
    initial.update(defaults or {})
    initial.pop("stage", None)  # always starts at CONTACT_TARGET; use change_stage() afterwards
    participation, created = Participation.objects.get_or_create(
        campaign=campaign, influencer=influencer, defaults=initial
    )
    if created:
        StatusLog.objects.create(
            participation=participation, from_stage="", to_stage=Stage.CONTACT_TARGET, changed_by=user
        )
    return participation, created
