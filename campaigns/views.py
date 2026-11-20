from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from influencers.models import Influencer

from . import selectors, services
from .forms import AddInfluencerForm, ParticipationForm
from .models import Campaign, Participation, Stage


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


@login_required
def dashboard(request):
    mine = request.GET.get("mine") == "1"
    return render(
        request,
        "campaigns/dashboard.html",
        {
            "summaries": selectors.campaign_summaries(),
            "alerts": selectors.dashboard_alerts(assignee=request.user if mine else None),
            "mine": mine,
        },
    )


def _board_context(campaign, assignee_id=None):
    qs = campaign.participations.select_related("influencer", "assignee")
    if assignee_id:
        qs = qs.filter(assignee_id=assignee_id)
    columns, closed = selectors.board_columns(qs)
    return {
        "campaign": campaign,
        "columns": columns,
        "closed": closed,
        "stage_choices": Stage.choices,
        "assignee_id": assignee_id,
    }


@login_required
def campaign_board(request, pk):
    campaign = get_object_or_404(Campaign.objects.select_related("client", "manager"), pk=pk)
    assignee_id = request.GET.get("assignee") or None
    context = _board_context(campaign, assignee_id)
    context.update(
        {
            "add_form": AddInfluencerForm(),
            "users": get_user_model().objects.filter(is_active=True).order_by("username"),
        }
    )
    return render(request, "campaigns/board.html", context)


@login_required
@require_POST
def campaign_add_influencers(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    form = AddInfluencerForm(request.POST)
    if not form.is_valid():
        for error in form.errors.get("handles", []):
            messages.error(request, error)
        return redirect("campaigns:board", pk=pk)

    added = 0
    for handle in form.cleaned_data["handles"]:
        influencer, _ = Influencer.objects.get_or_create(
            instagram_handle=handle, defaults={"owner": request.user, "source": Influencer.Source.MANUAL}
        )
        _, created = services.add_to_campaign(influencer, campaign, user=request.user)
        added += created
    skipped = len(form.cleaned_data["handles"]) - added
    messages.success(request, f"{added}명 추가" + (f" (이미 등록된 {skipped}명 제외)" if skipped else ""))
    return redirect("campaigns:board", pk=pk)


@login_required
@require_POST
def participation_change_stage(request, pk):
    participation = get_object_or_404(Participation.objects.select_related("campaign"), pk=pk)
    to_stage = request.POST.get("stage", "")
    error = None
    if to_stage not in Stage.values:
        error = "알 수 없는 단계입니다."
    else:
        try:
            services.change_stage(
                participation,
                to_stage,
                user=request.user,
                memo=request.POST.get("memo", "")[:300],
                force=request.POST.get("force") == "1",
            )
        except ValidationError as e:
            error = e.messages[0]

    if _is_htmx(request) and request.POST.get("from") == "board":
        context = _board_context(participation.campaign, request.POST.get("assignee") or None)
        context["error"] = error
        return render(request, "campaigns/_board.html", context)

    if error:
        messages.error(request, error)
    else:
        messages.success(request, f"단계를 '{participation.get_stage_display()}'(으)로 변경했습니다.")
    return redirect("campaigns:participation", pk=pk)


@login_required
def participation_detail(request, pk):
    participation = get_object_or_404(
        Participation.objects.select_related("campaign__client", "influencer", "assignee"), pk=pk
    )
    if request.method == "POST":
        form = ParticipationForm(request.POST, instance=participation)
        if form.is_valid():
            form.save()
            messages.success(request, "저장했습니다.")
            return redirect("campaigns:participation", pk=pk)
    else:
        form = ParticipationForm(instance=participation)
    return render(
        request,
        "campaigns/participation_detail.html",
        {
            "p": participation,
            "form": form,
            "logs": participation.status_logs.select_related("changed_by")[:50],
            "stage_choices": Stage.choices,
        },
    )
