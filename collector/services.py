"""해시태그 수집 → 후보 적재 → 승인(인플루언서 upsert + 캠페인 추가)."""

import logging

from django.db import transaction
from django.utils import timezone

from campaigns.services import add_to_campaign
from influencers.models import Influencer, is_valid_handle, normalize_handle

from .adapters import CollectedAccount, get_adapter
from .models import Candidate, HashtagJob

logger = logging.getLogger(__name__)


def normalize_hashtag(value: str) -> str:
    """'#성수 카페' 같은 공백 포함 값은 '' (해시태그가 아님)."""
    value = (value or "").strip().lstrip("#").lower()
    return value if value and len(value) <= 100 and all(c.isalnum() or c == "_" for c in value) else ""


def start_job(hashtag: str, limit: int, user=None) -> HashtagJob:
    from .tasks import run_hashtag_job

    job = HashtagJob.objects.create(hashtag=hashtag, limit=limit, requested_by=user)
    run_hashtag_job.enqueue(job.pk)
    job.refresh_from_db()
    return job


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


def run_job(job_id: int) -> None:
    # 대기 상태인 작업만 가져가므로 같은 작업이 두 번 실행되지 않는다.
    claimed = HashtagJob.objects.filter(pk=job_id, status=HashtagJob.Status.PENDING).update(
        status=HashtagJob.Status.RUNNING, started_at=timezone.now(), updated_at=timezone.now()
    )
    if not claimed:
        return
    job = HashtagJob.objects.get(pk=job_id)
    try:
        accounts = get_adapter().collect(job.hashtag, job.limit)
        candidates, skipped = build_candidates(job, accounts)
        with transaction.atomic():
            Candidate.objects.bulk_create(candidates)
            job.status = HashtagJob.Status.DONE
            job.result_count = len(candidates)
            job.skipped_count = skipped
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "result_count", "skipped_count", "finished_at", "updated_at"])
    except Exception as e:
        logger.exception("해시태그 수집 실패: job=%s", job_id)
        job.status = HashtagJob.Status.FAILED
        job.error = str(e)[:1000]
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at", "updated_at"])


def upsert_influencer(candidate: Candidate, user=None) -> Influencer:
    """계정 기준 upsert. 기존 계정은 빈 칸만 채워 사람이 입력한 값을 덮어쓰지 않는다."""
    hashtag = candidate.job.hashtag
    influencer, created = Influencer.objects.get_or_create(
        instagram_handle=candidate.handle,
        defaults={
            "account_name": candidate.account_name,
            "account_url": candidate.account_url,
            "follower_count": candidate.follower_count,
            "source": Influencer.Source.COLLECTOR,
            "discovered_hashtags": [hashtag],
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
    hashtags = list(influencer.discovered_hashtags or [])
    if hashtag not in hashtags:
        influencer.discovered_hashtags = [*hashtags, hashtag]
        changed.append("discovered_hashtags")
    if changed:
        influencer.save(update_fields=[*changed, "updated_at"])
    return influencer


@transaction.atomic
def approve_candidates(candidates, campaign, *, user=None) -> tuple[int, int]:
    """승인 → 인플루언서 upsert + 컨택 대상 추가. (새로 추가, 이미 캠페인에 있음)"""
    added = existing = 0
    for candidate in candidates.select_related("job"):
        influencer = upsert_influencer(candidate, user=user)
        _, created = add_to_campaign(influencer, campaign, user=user)
        added += created
        existing += not created
        candidate.influencer = influencer
        candidate.review_status = Candidate.ReviewStatus.APPROVED
        candidate.save(update_fields=["influencer", "review_status", "updated_at"])
    return added, existing


def reject_candidates(candidates) -> int:
    """검토 대기 건만 제외한다. 이미 승인된 건은 캠페인에 들어가 있으므로 건드리지 않는다."""
    return candidates.filter(review_status=Candidate.ReviewStatus.PENDING).update(
        review_status=Candidate.ReviewStatus.REJECTED, updated_at=timezone.now()
    )
