"""해시태그 수집 → 후보 적재 + 인플루언서 DB 자동 등록 → 캠페인에 추가(승인).

수집 방법은 세 가지이고, 끝나면 모두 finish_job()을 지난다.
- Apify(클라우드): start_job이 실행만 걸고, poll_job이 상태를 확인해 2단계(게시물 → 프로필)로 진행
- 연결된 스크래퍼(COLLECTOR_SCRAPER): 작업 큐에서 run_job
- 결과 파일 올리기(insta-finder): import_results
수집된 계정은 곧바로 인플루언서 DB에 등록된다(빈 칸만 채움). 캠페인 추가는 후보 검토에서 사람이 고른다.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from campaigns.services import add_to_campaign
from influencers.models import Influencer, is_valid_handle, normalize_handle

from . import importers
from .adapters import CollectedAccount, CollectorError, apify, get_adapter
from .adapters.scraper import to_account
from .classify import guess_category
from .models import Candidate, HashtagJob

logger = logging.getLogger(__name__)


def normalize_hashtag(value: str) -> str:
    """'#성수 카페' 같은 공백 포함 값은 '' (해시태그가 아님)."""
    value = (value or "").strip().lstrip("#").lower()
    return value if value and len(value) <= 100 and all(c.isalnum() or c == "_" for c in value) else ""


def collector_available() -> bool:
    return apify.ApifyClient.is_configured() or get_adapter().is_configured()


def start_job(hashtag: str, limit: int, user=None, *, category: str = "", campaign=None, client=None) -> HashtagJob:
    """Apify가 설정돼 있으면 Apify, 아니면 연결된 스크래퍼로 수집한다."""
    from .tasks import run_hashtag_job

    use_apify = apify.ApifyClient.is_configured()
    job = HashtagJob.objects.create(
        hashtag=hashtag,
        limit=limit,
        requested_by=user,
        category=category,
        campaign=campaign,
        source=HashtagJob.Source.APIFY if use_apify else HashtagJob.Source.SCRAPER,
    )
    if not use_apify:
        run_hashtag_job.enqueue(job.pk)
        job.refresh_from_db()
        return job
    client = client or apify.ApifyClient()
    try:
        run_id = client.start(settings.APIFY_HASHTAG_ACTOR, apify.hashtag_input(hashtag, limit))
    except CollectorError as e:
        _fail(job, e)
        return job
    job.status = HashtagJob.Status.RUNNING
    job.started_at = timezone.now()
    job.external = {"stage": "posts", "run_id": run_id}
    job.save(update_fields=["status", "started_at", "external", "updated_at"])
    return job


def poll_job(job_id: int, client=None) -> HashtagJob:
    """Apify 작업 상태 확인 → 다음 단계로. 아직 실행 중이면 그대로 둔다. 동시에 불러도 한 번만 진행된다."""
    client = client or apify.ApifyClient()
    with transaction.atomic():
        job = HashtagJob.objects.select_for_update().get(pk=job_id)
        if job.status != HashtagJob.Status.RUNNING or job.source != HashtagJob.Source.APIFY:
            return job
        external = dict(job.external)
        try:
            run = client.run(external.get("run_id", ""))
            status = run.get("status")
            if status in apify.FAILED_STATES:
                raise CollectorError(f"Apify 실행이 끝나지 못했습니다 ({status}).")
            if status != apify.SUCCEEDED:
                return job
            items = client.items(run.get("defaultDatasetId", ""))
            if external.get("stage") == "posts":
                accounts = apify.owners_from_posts(items, job.limit)
                if not accounts:
                    finish_job(job, [])
                    return job
                run_id = client.start(
                    settings.APIFY_PROFILE_ACTOR, apify.profile_input([a["handle"] for a in accounts])
                )
                job.external = {"stage": "profiles", "run_id": run_id, "accounts": accounts}
                job.save(update_fields=["external", "updated_at"])
                return job
            accounts = apify.merge_profiles(external.get("accounts", []), items)
            job.external = {"stage": "done", "run_id": external.get("run_id", "")}
            finish_job(job, [to_account(a) for a in accounts])
        except CollectorError as e:
            logger.warning("Apify 수집 실패: job=%s %s", job_id, e)
            _fail(job, e)
    return job


def poll_running_jobs(limit=20) -> int:
    ids = list(
        HashtagJob.objects.filter(status=HashtagJob.Status.RUNNING, source=HashtagJob.Source.APIFY)
        .order_by("started_at")
        .values_list("pk", flat=True)[:limit]
    )
    if ids:
        client = apify.ApifyClient()
        for job_id in ids:
            poll_job(job_id, client=client)
    return len(ids)


def import_results(uploaded, user=None, *, category: str = "", campaign=None) -> tuple[list[HashtagJob], list[str]]:
    """insta-finder 결과 파일 → 해시태그마다 완료된 수집 작업 1개. (만든 작업, 건너뛴 해시태그)"""
    groups = importers.parse_upload(uploaded)
    jobs, skipped = [], []
    for raw_tag, rows in groups.items():
        hashtag = normalize_hashtag(raw_tag)
        if not hashtag:
            skipped.append(raw_tag)
            continue
        job = HashtagJob.objects.create(
            hashtag=hashtag,
            limit=len(rows),
            requested_by=user,
            category=category,
            campaign=campaign,
            source=HashtagJob.Source.UPLOAD,
            status=HashtagJob.Status.RUNNING,
            started_at=timezone.now(),
        )
        finish_job(job, [to_account(row) for row in rows])
        jobs.append(job)
    return jobs, skipped


def build_candidates(job: HashtagJob, accounts: list[CollectedAccount]) -> tuple[list[Candidate], int]:
    """정규화·형식 검증·작업 내 중복 제거. (후보 목록, 제외 수)"""
    by_handle: dict[str, Candidate] = {}
    for account in accounts:
        handle = normalize_handle(account.handle)
        if not is_valid_handle(handle) or handle in by_handle:
            continue
        by_handle[handle] = Candidate(
            job=job,
            handle=handle,
            account_name=account.account_name,
            account_url=account.account_url or f"https://www.instagram.com/{handle}/",
            follower_count=account.follower_count,
            raw=account.raw,
        )
    return list(by_handle.values()), len(accounts) - len(by_handle)


def finish_job(job: HashtagJob, accounts: list[CollectedAccount]) -> None:
    """후보 저장 + 인플루언서 DB 자동 등록 + 작업 완료 처리."""
    candidates, skipped = build_candidates(job, accounts)
    with transaction.atomic():
        Candidate.objects.bulk_create(candidates, ignore_conflicts=True)
        saved = list(job.candidates.select_related("job").filter(influencer__isnull=True))
        for candidate in saved:
            candidate.influencer = upsert_influencer(candidate, user=job.requested_by)
        Candidate.objects.bulk_update(saved, ["influencer"])
        job.status = HashtagJob.Status.DONE
        job.result_count = job.candidates.count()
        job.skipped_count = skipped
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "result_count", "skipped_count", "finished_at", "external", "updated_at"])


def _fail(job: HashtagJob, error) -> None:
    job.status = HashtagJob.Status.FAILED
    job.error = str(error)[:1000]
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "error", "finished_at", "updated_at"])


def run_job(job_id: int) -> None:
    """연결된 스크래퍼로 수집 (작업 큐에서 실행)."""
    # 대기 상태인 작업만 가져가므로 같은 작업이 두 번 실행되지 않는다.
    claimed = HashtagJob.objects.filter(pk=job_id, status=HashtagJob.Status.PENDING).update(
        status=HashtagJob.Status.RUNNING, started_at=timezone.now(), updated_at=timezone.now()
    )
    if not claimed:
        return
    job = HashtagJob.objects.get(pk=job_id)
    try:
        finish_job(job, get_adapter().collect(job.hashtag, job.limit))
    except Exception as e:
        logger.exception("해시태그 수집 실패: job=%s", job_id)
        _fail(job, e)


def candidate_category(candidate: Candidate) -> str:
    raw = candidate.raw or {}
    return candidate.job.category or guess_category(
        candidate.job.hashtag, raw.get("business_category", ""), raw.get("biography", "")
    )


def upsert_influencer(candidate: Candidate, user=None) -> Influencer:
    """계정 기준 upsert. 기존 계정은 빈 칸만 채워 사람이 입력한 값을 덮어쓰지 않는다."""
    hashtag = candidate.job.hashtag
    category = candidate_category(candidate)
    influencer, created = Influencer.objects.get_or_create(
        instagram_handle=candidate.handle,
        defaults={
            "account_name": candidate.account_name,
            "account_url": candidate.account_url,
            "follower_count": candidate.follower_count,
            "source": Influencer.Source.COLLECTOR,
            "discovered_hashtags": [hashtag],
            "category": category,
            "owner": user,
        },
    )
    if created:
        return influencer

    changed = []
    for name in ("account_name", "account_url", "follower_count"):
        if getattr(influencer, name) in (None, "") and getattr(candidate, name) not in (None, ""):
            setattr(influencer, name, getattr(candidate, name))
            changed.append(name)
    if not influencer.category and category:
        influencer.category = category
        changed.append("category")
    hashtags = list(influencer.discovered_hashtags or [])
    if hashtag not in hashtags:
        influencer.discovered_hashtags = [*hashtags, hashtag]
        changed.append("discovered_hashtags")
    if changed:
        influencer.save(update_fields=[*changed, "updated_at"])
    return influencer


@transaction.atomic
def approve_candidates(candidates, campaign, *, user=None) -> tuple[int, int, int]:
    """승인 → 인플루언서 upsert + 컨택 대상 추가. (새로 추가, 이미 캠페인에 있음, 블랙리스트라 제외)

    블랙리스트 인플루언서 후보는 캠페인에 넣지 않고 '제외' 처리한다.
    """
    added = existing = blacklisted = 0
    for candidate in candidates.select_related("job"):
        influencer = upsert_influencer(candidate, user=user)
        if influencer.is_blacklisted and not campaign.participations.filter(influencer=influencer).exists():
            blacklisted += 1
            candidate.influencer = influencer
            candidate.review_status = Candidate.ReviewStatus.REJECTED
            candidate.save(update_fields=["influencer", "review_status", "updated_at"])
            continue
        _, created = add_to_campaign(influencer, campaign, user=user)
        added += created
        existing += not created
        candidate.influencer = influencer
        candidate.review_status = Candidate.ReviewStatus.APPROVED
        candidate.save(update_fields=["influencer", "review_status", "updated_at"])
    return added, existing, blacklisted


def reject_candidates(candidates) -> int:
    """검토 대기 건만 제외한다. 이미 승인된 건은 캠페인에 들어가 있으므로 건드리지 않는다."""
    return candidates.filter(review_status=Candidate.ReviewStatus.PENDING).update(
        review_status=Candidate.ReviewStatus.REJECTED, updated_at=timezone.now()
    )
