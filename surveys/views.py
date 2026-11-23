from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from campaigns.models import Campaign
from core.utils import parse_id

from . import services
from .google_forms import GoogleFormsError, service_account_email
from .models import UNIQUE_TARGETS, CampaignForm, FormResponse, Target


def _form_or_none(campaign):
    return CampaignForm.objects.filter(campaign=campaign).first()


@login_required
def survey_settings(request, pk):
    campaign = get_object_or_404(Campaign.objects.select_related("client"), pk=pk)
    cf = _form_or_none(campaign)
    context = {
        "campaign": campaign,
        "cf": cf,
        "service_account_email": service_account_email(),
        "target_choices": Target.choices,
    }
    if cf:
        questions = list(cf.questions.filter(is_active=True))
        unmatched = list(cf.responses.filter(participation__isnull=True))
        for resp in unmatched:
            resp.preview = [(q.title, ", ".join(resp.answers.get(q.question_id, []))) for q in questions[:6]]
        context.update(
            {
                "questions": questions,
                "removed_questions": cf.questions.filter(is_active=False),
                "unmatched": unmatched,
                "participations": campaign.participations.select_related("influencer").order_by(
                    "influencer__instagram_handle"
                ),
                "response_count": cf.responses.count(),
                "has_code_question": any(q.target == Target.PARTICIPATION_CODE for q in questions),
            }
        )
    return render(request, "surveys/settings.html", context)


def _run_sync(request, cf):
    try:
        result = services.sync_form(cf)
    except GoogleFormsError as e:
        messages.error(request, str(e))
        return
    messages.success(request, f"구글 폼 동기화 완료: {result.summary()}")


@login_required
@require_POST
def survey_connect(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    try:
        cf = services.connect_form(campaign, request.POST.get("form_url", ""))
    except GoogleFormsError as e:
        messages.error(request, str(e))
        return redirect("surveys:settings", pk=pk)
    messages.success(request, "구글 폼을 연결했습니다.")
    _run_sync(request, cf)
    return redirect("surveys:settings", pk=pk)


@login_required
@require_POST
def survey_sync(request, pk):
    cf = get_object_or_404(CampaignForm, campaign_id=pk)
    _run_sync(request, cf)
    return redirect("surveys:settings", pk=pk)


@login_required
@require_POST
def survey_questions(request, pk):
    """문항별 '옮겨 적을 칸' 저장. 같은 칸을 두 문항에 지정하면 거부."""
    cf = get_object_or_404(CampaignForm, campaign_id=pk)
    questions = list(cf.questions.filter(is_active=True))
    chosen = {}
    for q in questions:
        target = request.POST.get(f"target_{q.pk}", q.target)
        chosen[q.pk] = target if target in Target.values else q.target
    used = [t for t in chosen.values() if t in UNIQUE_TARGETS]
    duplicates = {Target(t).label for t in used if used.count(t) > 1}
    if duplicates:
        messages.error(request, f"한 칸에는 문항 하나만 지정할 수 있습니다: {', '.join(sorted(duplicates))}")
        return redirect("surveys:settings", pk=pk)
    for q in questions:
        q.target = chosen[q.pk]
        q.include_in_client_export = request.POST.get(f"client_{q.pk}") == "1"
        q.save(update_fields=["target", "include_in_client_export"])
    if request.POST.get("reapply") == "1":
        count = services.reapply_all(cf, user=request.user)
        messages.success(request, f"매핑을 저장하고 응답 {count}건을 다시 옮겨 적었습니다.")
    else:
        messages.success(request, "매핑을 저장했습니다. 새로 가져오는 응답부터 적용됩니다.")
    return redirect("surveys:settings", pk=pk)


@login_required
@require_POST
def survey_link_response(request, pk, response_pk):
    resp = get_object_or_404(FormResponse.objects.select_related("form__campaign"), pk=response_pk, form__campaign_id=pk)
    participation = None
    if request.POST.get("action") != "create":
        participation_id = parse_id(request.POST.get("participation"))
        participation = resp.form.campaign.participations.filter(pk=participation_id).first()
        if participation is None:
            messages.error(request, "연결할 인플루언서를 선택하세요.")
            return redirect("surveys:settings", pk=pk)
    try:
        participation = services.link_response(resp, participation, user=request.user)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect("surveys:settings", pk=pk)
    messages.success(request, f"응답을 {participation.influencer}에 연결하고 옮겨 적었습니다.")
    return redirect("surveys:settings", pk=pk)
