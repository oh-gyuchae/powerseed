from django.db.models import Count, Exists, OuterRef, Q

from campaigns.models import Campaign
from influencers.models import Influencer

from .models import Candidate, HashtagJob


def recent_jobs(limit=50):
    pending = Count("candidates", filter=Q(candidates__review_status=Candidate.ReviewStatus.PENDING))
    return HashtagJob.objects.select_related("requested_by").annotate(pending_count=pending)[:limit]


def job_candidates(job, *, status="", min_followers=None):
    qs = job.candidates.annotate(
        is_known=Exists(Influencer.objects.filter(instagram_handle=OuterRef("handle")))
    )
    if status in Candidate.ReviewStatus.values:
        qs = qs.filter(review_status=status)
    if min_followers is not None:
        qs = qs.filter(follower_count__gte=min_followers)
    return qs


def open_campaigns():
    return Campaign.objects.filter(status__in=[Campaign.Status.PLANNING, Campaign.Status.ACTIVE]).select_related(
        "client"
    )
