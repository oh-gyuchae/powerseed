"""콘텐츠 성과 계산 열 + 리포트(시트 ⑤ 대시보드) 집계.

비용 배분: 참여 건 총비용(performance.costs.CostBook)을 그 참여 건의 게시물 수로 나눠 게시물마다 배분한다.
- 참여율 = (좋아요+댓글+저장+공유) ÷ 조회수 × 100
- CPV = 비용 ÷ 조회수, CPM = 비용 ÷ 조회수 × 1,000
- ROAS(%) = 매출 ÷ 비용 × 100
캠페인·인플루언서 합계의 CPV·ROAS는 행 평균이 아니라 '총비용 ÷ 총조회수', '총매출 ÷ 총비용'이다
(조회수가 적은 게시물 하나가 평균을 왜곡하지 않도록).
"""

from collections import defaultdict

from django.db.models import Count

from campaigns.models import CONTRACT_STAGE, REPLY_STAGE, Campaign, Participation, Stage, StatusLog
from core.choices import Country
from .costs import CostBook
from .models import ContentPost

TOP_ORDERS = {
    "cpv": "CPV 낮은 순",
    "roas": "ROAS 높은 순",
    "views": "조회수 많은 순",
}


def _ratio(numerator, denominator, scale=1, digits=2):
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator * scale, digits)


def _fill_rates(target, cost, views, revenue):
    target.cost_krw = cost or None
    target.cpv = _ratio(cost, views) if cost else None
    target.cpm = _ratio(cost, views, 1000, 0) if cost else None
    target.roas = _ratio(revenue, cost, 100, 1) if revenue is not None and cost else None
    return target


def posts(campaign_id=None):
    qs = ContentPost.objects.select_related(
        "participation__campaign__client", "participation__influencer"
    )
    if campaign_id:
        qs = qs.filter(participation__campaign_id=campaign_id)
    return qs.annotate(siblings=Count("participation__posts"))


def with_metrics(post_qs, book=None):
    """게시물마다 cost_krw·cpv·cpm·roas 속성을 붙여 리스트로 돌려준다. `post_qs`는 posts()의 결과."""
    book = book or CostBook()
    costs = {}
    rows = []
    for post in post_qs:
        pid = post.participation_id
        if pid not in costs:
            costs[pid] = book.participation_cost(post.participation)
        share = round(costs[pid] / post.siblings) if costs[pid] else 0
        rows.append(_fill_rates(post, share, post.views, post.revenue))
    return rows


# ---------------------------------------------------------------- 리포트


def _reached_stages(participations):
    reached = defaultdict(set)
    logs = StatusLog.objects.filter(participation__in=participations).values_list("participation_id", "to_stage")
    for pid, stage in logs:
        reached[pid].add(stage)
    return reached


def _reached(pipeline, stages, reference):
    position = pipeline.index(reference)
    return any(s in pipeline and pipeline.index(s) >= position for s in stages)


def country_funnel(kind=None):
    """국가별 섭외 수 → 회신 → 계약. 단계 변경 이력으로 '한 번이라도 도달했는지'를 본다 (지금 거절 상태여도 회신은 센다).

    섭외 = 컨택 대상에서 한 단계라도 넘어간 건 / 회신 = 회신 단계 이상 또는 거절 / 계약 = 확정(계약) 단계 이상
    """
    qs = Participation.objects.select_related("campaign", "influencer")
    if kind:
        qs = qs.filter(campaign__kind=kind)
    reached = _reached_stages(qs)
    totals = defaultdict(lambda: {"contacted": 0, "replied": 0, "contracted": 0})
    for p in qs:
        stages = reached[p.pk] | {p.stage}
        if not any(s != Stage.CONTACT_TARGET for s in stages):
            continue
        pipeline = p.campaign.pipeline
        row = totals[p.influencer.country]
        row["contacted"] += 1
        if _reached(pipeline, stages, REPLY_STAGE[p.campaign.kind]) or Stage.DECLINED in stages:
            row["replied"] += 1
        if _reached(pipeline, stages, CONTRACT_STAGE[p.campaign.kind]):
            row["contracted"] += 1

    rows = []
    for code, row in totals.items():
        rows.append(
            {
                "country": Country(code).label if code else "미입력",
                **row,
                "reply_rate": _ratio(row["replied"], row["contacted"], 100, 1),
                "contract_rate": _ratio(row["contracted"], row["replied"], 100, 1),
            }
        )
    return sorted(rows, key=lambda r: (-r["contacted"], r["country"]))


def _participations_with_costs():
    return Participation.objects.select_related("campaign", "influencer").prefetch_related("posts")


def campaign_performance(kind=None):
    """캠페인별 총비용(원)·총조회수·CPV·ROAS."""
    book = CostBook()
    campaigns = Campaign.objects.select_related("client").order_by("-created_at")
    if kind:
        campaigns = campaigns.filter(kind=kind)
    by_campaign = defaultdict(list)
    for p in _participations_with_costs().filter(campaign__in=campaigns):
        by_campaign[p.campaign_id].append(p)

    rows = []
    for campaign in campaigns:
        participations = by_campaign.get(campaign.pk, [])
        if not participations:
            continue
        posts = [post for p in participations for post in p.posts.all()]
        cost = sum(book.participation_cost(p) for p in participations)
        views = sum(post.views or 0 for post in posts)
        revenue = sum(post.revenue or 0 for post in posts) if any(post.revenue is not None for post in posts) else None
        row = {
            "campaign": campaign,
            "contracted": sum(p.is_committed for p in participations),
            "posts": len(posts),
            "views": views,
            "revenue": revenue,
        }
        rows.append(_fill_rates(_Row(row), cost, views, revenue))
    return rows, book.missing_rates


class _Row(dict):
    """템플릿에서 row.cpv 처럼 읽을 수 있는 dict."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def __setattr__(self, name, value):
        self[name] = value


def top_influencers(order="cpv", limit=10, kind=None):
    """게시물이 있는 인플루언서를 캠페인 전체에서 합산해 순위를 매긴다 (재협업 후보)."""
    book = CostBook()
    qs = _participations_with_costs().filter(posts__isnull=False).distinct()
    if kind:
        qs = qs.filter(campaign__kind=kind)
    totals = {}
    for p in qs:
        posts = list(p.posts.all())
        row = totals.setdefault(
            p.influencer_id,
            {"influencer": p.influencer, "campaigns": 0, "posts": 0, "cost": 0, "views": 0, "revenue": None, "_er": []},
        )
        row["campaigns"] += 1
        row["posts"] += len(posts)
        row["cost"] += book.participation_cost(p)
        row["views"] += sum(post.views or 0 for post in posts)
        revenues = [post.revenue for post in posts if post.revenue is not None]
        if revenues:
            row["revenue"] = (row["revenue"] or 0) + sum(revenues)
        row["_er"] += [post.engagement_rate for post in posts if post.engagement_rate is not None]

    rows = []
    for row in totals.values():
        er = row.pop("_er")
        row = _Row(row, engagement_rate=round(sum(er) / len(er), 2) if er else None)
        rows.append(_fill_rates(row, row["cost"], row["views"], row["revenue"]))

    if order == "roas":
        rows = sorted((r for r in rows if r.roas is not None), key=lambda r: -r.roas)
    elif order == "views":
        rows = sorted(rows, key=lambda r: -r.views)
    else:
        rows = sorted((r for r in rows if r.cpv is not None), key=lambda r: r.cpv)
    return rows[:limit]
