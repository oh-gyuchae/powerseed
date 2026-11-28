from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import selectors, services
from .adapters import CollectorError
from .forms import HashtagJobForm, ResultUploadForm
from .models import Candidate, HashtagJob


def _parse_count(value):
    value = (value or "").strip()
    return int(value) if value.isascii() and value.isdigit() and len(value) <= 10 else None


@login_required
def job_list(request):
    configured = services.collector_available()
    form = HashtagJobForm(initial={"limit": settings.COLLECTOR_DEFAULT_LIMIT})
    upload_form = ResultUploadForm()
    if request.method == "POST" and request.POST.get("action") == "upload":
        upload_form = ResultUploadForm(request.POST, request.FILES)
        if upload_form.is_valid():
            data = upload_form.cleaned_data
            try:
                jobs, skipped = services.import_results(
                    data["file"], request.user, category=data["category"], campaign=data["campaign"]
                )
            except CollectorError as e:
                messages.error(request, str(e))
            else:
                total = sum(job.result_count for job in jobs)
                messages.success(request, f"해시태그 {len(jobs)}개, 계정 {total}명을 불러와 인플루언서 DB에 등록했습니다.")
                if skipped:
                    messages.warning(request, f"해시태그 형식이 아니라 건너뜀: {', '.join(skipped)}")
                if len(jobs) == 1:
                    return redirect("collector:review", pk=jobs[0].pk)
                return redirect("collector:jobs")
    elif request.method == "POST":
        form = HashtagJobForm(request.POST)
        if not configured:
            messages.error(request, "수집기가 연결되지 않아 실행할 수 없습니다.")
        elif form.is_valid():
            data = form.cleaned_data
            job = services.start_job(
                data["hashtag"], data["limit"], request.user, category=data["category"], campaign=data["campaign"]
            )
            if job.status == HashtagJob.Status.FAILED:
                messages.error(request, f"#{job.hashtag} 수집 실패: {job.error}")
            elif job.status == HashtagJob.Status.RUNNING:
                messages.success(request, f"#{job.hashtag} 수집을 시작했습니다. 몇 분 걸립니다 (이 화면은 자동으로 새로고침됩니다).")
            else:
                messages.success(request, f"#{job.hashtag} 수집 작업을 실행했습니다.")
            return redirect("collector:review", pk=job.pk)
    return render(
        request,
        "collector/jobs.html",
        {
            "form": form,
            "upload_form": upload_form,
            "jobs": selectors.recent_jobs(),
            "configured": configured,
            "has_running": selectors.has_running_jobs(),
        },
    )


@login_required
def jobs_poll(request):
    """수집 중인 Apify 작업 상태 확인 → 작업 표 부분 갱신 (HTMX 5초 간격)."""
    services.poll_running_jobs()
    return render(
        request,
        "collector/_jobs_table.html",
        {"jobs": selectors.recent_jobs(), "has_running": selectors.has_running_jobs()},
    )


@login_required
def job_poll(request, pk):
    """후보 검토 화면에서 수집 중인 작업 확인. 끝나면 화면 전체를 새로고침한다."""
    job = get_object_or_404(HashtagJob, pk=pk)
    job = services.poll_job(job.pk)
    if job.status == HashtagJob.Status.RUNNING:
        return render(request, "collector/_job_running.html", {"job": job})
    response = HttpResponse("")
    response["HX-Refresh"] = "true"
    return response


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
            "default_campaign_id": job.campaign_id,
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
