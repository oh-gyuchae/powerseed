import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from campaigns.models import Campaign, Participation
from core.utils import parse_id

from . import services
from .models import Channel, Message, MessageTemplate
from .providers import PROVIDERS, ProviderError, get_provider
from .providers.instagram import InstagramProvider

logger = logging.getLogger(__name__)


def compose_context(participation, channel=None, template_id=None, subject=None, body=None):
    """참여 상세 화면의 메시지 발송 영역."""
    reasons = {key: cls().unavailable_reason(participation) for key, cls in PROVIDERS.items()}
    if channel not in PROVIDERS:
        channel = next((key for key, reason in reasons.items() if reason is None), Channel.INSTAGRAM)
    templates = MessageTemplate.objects.filter(Q(channel="") | Q(channel=channel))
    template = templates.filter(pk=template_id).first() if template_id else None
    if template is not None:
        subject = services.render_template(template.subject, participation)
        body = services.render_template(template.body, participation)
    provider = get_provider(channel)
    return {
        "p": participation,
        "channel": channel,
        "channel_choices": Channel.choices,
        "reason": reasons[channel],
        "recipient": provider.recipient(participation),
        "supports_subject": provider.supports_subject,
        "templates": templates,
        "template_id": template.pk if template else None,
        "subject": subject or "",
        "body": body or "",
        "survey_link": services.survey_link(participation),
    }


def message_history(participation, limit=30):
    return (
        Message.objects.filter(Q(participation=participation) | Q(influencer=participation.influencer))
        .select_related("sent_by", "participation__campaign")
        .order_by("-created_at")[:limit]
    )


@login_required
def compose(request, pk):
    participation = get_object_or_404(Participation.objects.select_related("campaign", "influencer"), pk=pk)
    context = compose_context(
        participation, request.GET.get("channel"), parse_id(request.GET.get("template"))
    )
    return render(request, "messaging/_compose.html", context)


@login_required
@require_POST
def send(request, pk):
    participation = get_object_or_404(Participation.objects.select_related("campaign", "influencer"), pk=pk)
    channel = request.POST.get("channel", "")
    manual = request.POST.get("manual") == "1"
    try:
        if manual:
            message = services.record_manual_message(
                participation, channel, body=request.POST.get("body", ""), user=request.user
            )
        else:
            message = services.send_message(
                participation,
                channel,
                subject=request.POST.get("subject", "")[:200],
                body=request.POST.get("body", ""),
                user=request.user,
            )
    except ProviderError as e:
        messages.error(request, str(e))
    else:
        done = "직접 발송 기록" if manual else "발송 완료"
        messages.success(request, f"{message.get_channel_display()} {done}: {message.recipient}")
    return redirect("campaigns:participation", pk=pk)


# ---------------------------------------------------------------- 캠페인 일괄 DM


OUTREACH_STAGES = ("contact_target", "contacted")


def _outreach_row(participation, template, user=None, sent=None):
    body = services.render_template(template.body, participation) if template else ""
    provider = get_provider(Channel.INSTAGRAM)
    return {
        "p": participation,
        "body": body,
        "dm_url": f"https://ig.me/m/{participation.influencer.instagram_handle}",
        "api_ready": provider.unavailable_reason(participation) is None,
        "sent": sent,
    }


@login_required
def outreach(request, campaign_pk):
    """캠페인 일괄 DM: 템플릿을 고르면 인플루언서마다 문구(전용 설문 링크 포함)를 만들어 준다.

    첫 DM은 API로 보낼 수 없어(Meta 정책) '복사 → 인스타 DM 열기 → 보냄 기록' 순서로 보낸다.
    상대가 답장한 지 24시간 안이면 'API로 보내기'가 켜진다.
    """
    campaign = get_object_or_404(Campaign, pk=campaign_pk)
    templates = MessageTemplate.objects.filter(Q(channel="") | Q(channel=Channel.INSTAGRAM))
    template = templates.filter(pk=parse_id(request.GET.get("template"))).first() or templates.first()
    stage = request.GET.get("stage") if request.GET.get("stage") in OUTREACH_STAGES else "contact_target"
    participations = (
        campaign.participations.filter(stage=stage).select_related("influencer", "campaign").order_by("influencer__instagram_handle")
    )
    return render(
        request,
        "messaging/outreach.html",
        {
            "campaign": campaign,
            "templates": templates,
            "template": template,
            "stage": stage,
            "stage_choices": [(value, label) for value, label in campaign.stage_choices if value in OUTREACH_STAGES],
            "rows": [_outreach_row(p, template) for p in participations],
        },
    )


@login_required
@require_POST
def outreach_send(request, pk):
    """일괄 DM 한 줄: mode=manual(직접 보냄 기록) / api(API 발송). 그 줄만 다시 그린다."""
    participation = get_object_or_404(Participation.objects.select_related("campaign", "influencer"), pk=pk)
    body = request.POST.get("body", "")
    try:
        if request.POST.get("mode") == "api":
            services.send_message(participation, Channel.INSTAGRAM, body=body, user=request.user)
        else:
            services.record_manual_message(participation, Channel.INSTAGRAM, body=body, user=request.user)
    except ProviderError as e:
        row = _outreach_row(participation, None)
        row.update(body=body, error=str(e))
        return render(request, "messaging/_outreach_row.html", {"row": row})
    participation.refresh_from_db()
    row = _outreach_row(participation, None, sent=True)
    row["body"] = body
    return render(request, "messaging/_outreach_row.html", {"row": row})


@csrf_exempt
def webhook(request, provider):
    """Meta(인스타그램) 웹훅: GET = 등록 확인, POST = 메시지 수신. 서명 검증 실패 시 403."""
    if provider != Channel.INSTAGRAM:
        raise Http404
    if request.method == "GET":
        challenge = InstagramProvider.verify_challenge(request.GET)
        return HttpResponse(challenge) if challenge is not None else HttpResponseForbidden()
    if request.method != "POST":
        return HttpResponseBadRequest()
    if not InstagramProvider.verify_signature(request.body, request.headers.get("X-Hub-Signature-256", "")):
        return HttpResponseForbidden()
    try:
        payload = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest()
    try:
        services.handle_instagram_webhook(payload)
    except Exception:  # Meta는 실패 응답 시 재전송하므로, 오류는 기록만 하고 200으로 받는다
        logger.exception("instagram webhook handling failed")
    return HttpResponse("ok")
