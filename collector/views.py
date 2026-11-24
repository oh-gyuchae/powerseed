from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import selectors, services
from .adapters import get_adapter
from .forms import HashtagJobForm
from .models import Candidate, HashtagJob


def _parse_count(value):
    value = (value or "").strip()
    return int(value) if value.isascii() and value.isdigit() and len(value) <= 10 else None


@login_required
def job_list(request):
    configured = get_adapter().is_configured()
    if request.method == "POST":
        form = HashtagJobForm(request.POST)
        if not configured:
            messages.error(request, "수집기가 연결되지 않아 실행할 수 없습니다.")
        elif form.is_valid():
            job = services.start_job(form.cleaned_data["hashtag"], form.cleaned_data["limit"], request.user)
            if job.status == HashtagJob.Status.FAILED:
                messages.error(request, f"#{job.hashtag} 수집 실패: {job.error}")
            else:
                messages.success(request, f"#{job.hashtag} 수집 작업을 실행했습니다.")
            return redirect("collector:review", pk=job.pk)
    else:
        form = HashtagJobForm(initial={"limit": settings.COLLECTOR_DEFAULT_LIMIT})
    return render(
        request,
        "collector/jobs.html",
        {"form": form, "jobs": selectors.recent_jobs(), "configured": configured},
    )


@login_required
def job_review(request, pk):
    job = get_object_or_404(HashtagJob, pk=pk)
    status = request.GET.get("status", Candidate.ReviewStatus.PENDING)
    min_followers = _parse_count(request.GET.get("min_followers"))
    candidates = selectors.job_candidates(job, status=status, min_followers=min_followers)
    page = Paginator(candidates, 100).get_page(request.GET.get("page"))
    return render(
        request,
        "collector/review.html",
        {
            "job": job,
            "page": page,
            "status": status,
            "min_followers": min_followers,
            "status_choices": Candidate.ReviewStatus.choices,
            "campaigns": selectors.open_campaigns(),
        },
    )


@login_required
@require_POST
def job_bulk(request, pk):
    job = get_object_or_404(HashtagJob, pk=pk)
    back = reverse("collector:review", args=[pk])
    if request.GET:
        back += f"?{request.GET.urlencode()}"

    ids = [int(v) for v in request.POST.getlist("ids") if v.isascii() and v.isdigit() and len(v) <= 18]
    selected = job.candidates.filter(pk__in=ids)
    if not selected.exists():
        messages.error(request, "후보를 선택하세요.")
        return redirect(back)

    action = request.POST.get("action")
    if action == "reject":
        count = services.reject_candidates(selected)
        messages.success(request, f"{count}명을 제외했습니다.")
    elif action == "approve":
        campaign_id = _parse_count(request.POST.get("campaign"))
        campaign = selectors.open_campaigns().filter(pk=campaign_id).first() if campaign_id else None
        if campaign is None:
            messages.error(request, "추가할 캠페인을 선택하세요.")
            return redirect(back)
        added, existing, blacklisted = services.approve_candidates(selected, campaign, user=request.user)
        excluded = [f"이미 등록된 {existing}명" if existing else "", f"블랙리스트 {blacklisted}명" if blacklisted else ""]
        excluded = ", ".join(x for x in excluded if x)
        suffix = f" ({excluded} 제외)" if excluded else ""
        messages.success(request, f"'{campaign.name}'에 {added}명 추가{suffix}")
    else:
        messages.error(request, "알 수 없는 작업입니다.")
    return redirect(back)
