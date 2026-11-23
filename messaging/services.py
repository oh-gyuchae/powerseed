from datetime import datetime
from datetime import timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

from campaigns import services as campaign_services
from campaigns.models import Stage
from influencers.models import Influencer, normalize_handle
from surveys.services import survey_link

from .models import Channel, InstagramThread, Message
from .providers import ProviderError, get_provider
from .providers.instagram import InstagramProvider

# 설문 링크가 든 메시지를 보내면 '설문 발송'으로 옮길 단계
_BEFORE_SURVEY_SENT = {Stage.CONTACT_TARGET, Stage.CONTACTED}


def template_variables(participation):
    influencer = participation.influencer
    return {
        "이름": influencer.account_name or influencer.instagram_handle,
        "계정": f"@{influencer.instagram_handle}",
        "캠페인": participation.campaign.name,
        "방문장소": participation.campaign.visit_location,
        "설문링크": survey_link(participation),
    }


def render_template(text, participation):
    for key, value in template_variables(participation).items():
        text = text.replace("{{" + key + "}}", value or "")
    return text


def send_message(participation, channel, *, subject="", body, user=None, provider=None) -> Message:
    """발송 + 기록. 실패해도 Message(status=failed)를 남기고 ProviderError를 다시 던진다."""
    provider = provider or get_provider(channel)
    body = body.strip()
    if not body:
        raise ProviderError("내용을 입력하세요.")
    reason = provider.unavailable_reason(participation)
    if reason:
        raise ProviderError(reason)

    message = Message(
        channel=channel,
        direction=Message.Direction.OUT,
        influencer=participation.influencer,
        participation=participation,
        recipient=provider.recipient(participation),
        subject=subject if provider.supports_subject else "",
        body=body,
        sent_by=user,
    )
    if channel == Channel.INSTAGRAM:
        message.thread = provider.thread_for(participation)
    try:
        message.external_id = provider.send(participation, subject=subject, body=body)
    except ProviderError as e:
        message.status, message.error = Message.Status.FAILED, str(e)
        message.save()
        raise
    message.status = Message.Status.SENT
    message.save()

    link = survey_link(participation)
    if link and link in body and participation.stage in _BEFORE_SURVEY_SENT:
        campaign_services.change_stage(
            participation, Stage.SURVEY_SENT, user=user, memo=f"{message.get_channel_display()}로 설문 링크 발송"
        )
    return message


# ---------------------------------------------------------------- 인스타 웹훅


def handle_instagram_webhook(payload, provider: InstagramProvider | None = None) -> int:
    """수신/에코 메시지를 대화·메시지로 저장. 처리한 새 메시지 수를 돌려준다."""
    provider = provider or InstagramProvider()
    saved = 0
    for event in provider.parse_events(payload):
        with transaction.atomic():
            if Message.objects.filter(channel=Channel.INSTAGRAM, external_id=event["mid"]).exists():
                continue  # 이미 저장됨 (API로 보낸 메시지의 에코 포함)
            thread = _thread_for(event["igsid"], provider)
            at = _from_ms(event["timestamp"])
            if not event["is_echo"] and (thread.last_inbound_at is None or at > thread.last_inbound_at):
                thread.last_inbound_at = at
                thread.save(update_fields=["last_inbound_at", "updated_at"])
            Message.objects.create(
                channel=Channel.INSTAGRAM,
                direction=Message.Direction.OUT if event["is_echo"] else Message.Direction.IN,
                status=Message.Status.SENT if event["is_echo"] else Message.Status.RECEIVED,
                influencer=thread.influencer,
                thread=thread,
                recipient=f"@{thread.username}" if thread.username else thread.igsid,
                body=event["text"],
                external_id=event["mid"],
            )
            saved += 1
    return saved


def _thread_for(igsid, provider):
    thread, _ = InstagramThread.objects.get_or_create(igsid=igsid)
    if not thread.username:
        thread.username = normalize_handle(provider.fetch_username(igsid))
    if thread.influencer_id is None and thread.username:
        thread.influencer = Influencer.objects.filter(instagram_handle=thread.username).first()
    thread.save()
    return thread


def link_thread(thread: InstagramThread, influencer):
    """자동 매칭이 안 된 대화를 인플루언서에 수동 연결 (지난 메시지도 함께)."""
    thread.influencer = influencer
    thread.save(update_fields=["influencer", "updated_at"])
    thread.messages.filter(influencer__isnull=True).update(influencer=influencer)


def _from_ms(ms):
    if not ms:
        return timezone.now()
    return datetime.fromtimestamp(int(ms) / 1000, tz=dt_timezone.utc)
