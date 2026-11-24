"""Business logic for the seeding pipeline.

All stage changes must go through `change_stage` so that every transition is
logged (StatusLog) and stage-dependent fields stay consistent.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import CLOSED_STAGES, Participation, Stage, StatusLog


def _before(pipeline, to_stage, reference):
    """to_stage가 파이프라인에서 reference보다 앞인가 (reference가 없는 유형이면 False)."""
    return reference in pipeline and pipeline.index(to_stage) < pipeline.index(reference)


@transaction.atomic
def change_stage(participation: Participation, to_stage: str, *, user=None, memo: str = "", force=False):
    """Move a participation to `to_stage`, logging the change.

    Closed participations (paid / declined / dropped / no response) can only be reopened with
    `force=True`, so a finished payout is never silently undone.
    Only the stages of the campaign's kind (방문형 / 배송형) are allowed.
    """
    to_stage = Stage(to_stage)
    campaign = participation.campaign
    if to_stage not in campaign.stages:
        raise ValidationError(f"'{to_stage.label}' 단계는 {campaign.get_kind_display()} 캠페인에 없습니다.")
    from_stage = participation.stage
    if from_stage == to_stage:
        return participation
    if from_stage in CLOSED_STAGES and not force:
        raise ValidationError(f"종료된 건({Stage(from_stage).label})은 force=True 로만 변경할 수 있습니다.")

    now = timezone.now()
    participation.stage = to_stage
    update_fields = ["stage", "updated_at"]

    def clear(field, empty=None):
        if getattr(participation, field) != empty:
            setattr(participation, field, empty)
            update_fields.append(field)

    # 되돌리기(재오픈) 정책: 파이프라인 앞 단계로 돌아가면 그 이후에 기록된 사실을 지운다.
    # 거절/이탈/무응답으로 가는 경우는 되돌리기가 아니므로 기록을 유지한다.
    pipeline = campaign.pipeline
    if to_stage in pipeline:
        if _before(pipeline, to_stage, Stage.PAID):
            clear("paid_at")
        # 방문형은 '지급 대기' 앞, 배송형(지급 대기 단계 없음)은 '지급 완료' 앞으로 가면 미지급
        payout_reference = Stage.PAYOUT_PENDING if Stage.PAYOUT_PENDING in pipeline else Stage.PAID
        if _before(pipeline, to_stage, payout_reference):
            clear("payout_status", Participation.PayoutStatus.UNPAID)
        if _before(pipeline, to_stage, Stage.UPLOADED):
            clear("uploaded_at")
        if _before(pipeline, to_stage, Stage.RECEIVED):
            clear("received_at")
        if _before(pipeline, to_stage, Stage.SHIPPED):
            clear("shipped_at")
    if from_stage == Stage.DECLINED:
        participation.participation_status = Participation.ParticipationStatus.NO_RESPONSE
        update_fields.append("participation_status")

    # 도착 단계에 맞춰 연관 필드 동기화 (재오픈 초기화보다 우선)
    today = timezone.localdate()
    if to_stage == Stage.DECLINED:
        participation.participation_status = Participation.ParticipationStatus.NO
        update_fields.append("participation_status")
    elif to_stage in (Stage.CONFIRMED, Stage.CONTRACTED):
        participation.participation_status = Participation.ParticipationStatus.YES
        update_fields.append("participation_status")
    elif to_stage == Stage.SHIPPED and not participation.shipped_at:
        participation.shipped_at = today
        update_fields.append("shipped_at")
    elif to_stage == Stage.RECEIVED and not participation.received_at:
        participation.received_at = today
        update_fields.append("received_at")
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

    participation.save(update_fields=list(dict.fromkeys(update_fields)))
    StatusLog.objects.create(
        participation=participation, from_stage=from_stage, to_stage=to_stage, changed_by=user, memo=memo
    )
    return participation


@transaction.atomic
def add_to_campaign(influencer, campaign, *, user=None, defaults=None) -> tuple[Participation, bool]:
    """Register an influencer as a contact target for a campaign (idempotent).

    `defaults` overrides initial field values, and is only applied when a new row is created.
    Blacklisted influencers can't be newly added (ValidationError); existing rows are returned as-is.
    """
    existing = Participation.objects.filter(campaign=campaign, influencer=influencer).first()
    if existing:
        return existing, False
    if influencer.is_blacklisted:
        raise ValidationError(f"{influencer}은(는) 블랙리스트에 있어 추가할 수 없습니다.")
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
