"""캠페인 시트 열 정의 — 화면 표·CSV·엑셀 내보내기가 모두 이 목록 하나를 쓴다.

열을 추가/삭제/순서 변경하려면 COLUMNS만 고치면 된다.
- `kinds`로 방문형/배송형 캠페인 중 어디에 보일지 정한다 (비우면 두 유형 모두).
- `internal=True` 열은 사내용 내보내기에만 들어가고, 고객사 전달용 파일에서는 빠진다.
- `field`가 있는 열은 시트 화면에서 바로 수정할 수 있다 (ParticipationForm / stage 필드 이름).
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from django.utils import timezone

VISIT = ("visit",)
SHIPPING = ("shipping",)


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    get: Callable[[Any], Any]  # 행 객체(Participation 등) -> 원본 값 (int / Decimal / str / date / datetime / None)
    field: str | None = None
    internal: bool = False
    width: int = 14  # 엑셀 열 너비
    kinds: tuple = ()  # 이 열을 쓰는 캠페인 유형 (비우면 모든 유형)


def _local(dt):
    return timezone.localtime(dt) if dt else None


def yes_no(value):
    return "예" if value else "아니오"


COLUMNS = [
    Column("instagram_handle", "인스타 계정", lambda p: p.influencer.instagram_handle, width=20),
    Column("code", "인플루언서 ID", lambda p: p.influencer.code, kinds=SHIPPING, width=11),
    Column("account_name", "계정 이름", lambda p: p.influencer.account_name),
    Column("platform", "플랫폼", lambda p: p.influencer.get_platform_display(), width=10),
    Column("country", "국가", lambda p: p.influencer.get_country_display(), kinds=SHIPPING, width=10),
    Column("category", "카테고리", lambda p: p.influencer.get_category_display(), kinds=SHIPPING, width=10),
    Column("account_url", "계정 URL", lambda p: p.influencer.account_url, width=36),
    Column("follower_count", "팔로워 수", lambda p: p.influencer.follower_count, width=11),
    Column("monthly_reels_avg", "한 달 릴스 평균", lambda p: p.influencer.monthly_reels_avg, width=13),
    Column("engagement_rate", "참여율(%)", lambda p: p.influencer.engagement_rate, kinds=SHIPPING, width=10),
    Column("stage", "진행 단계", lambda p: p.get_stage_display(), field="stage", width=12),
    Column(
        "participation_status",
        "참여 의사",
        lambda p: p.get_participation_status_display(),
        field="participation_status",
        width=10,
    ),
    Column(
        "collab_type", "협업 유형", lambda p: p.get_collab_type_display(), field="collab_type", kinds=SHIPPING, width=12
    ),
    Column("deliverables", "결과물", lambda p: p.deliverables, field="deliverables", kinds=SHIPPING, width=20),
    Column(
        "available_visit_dates",
        "방문 가능일",
        lambda p: ", ".join(p.available_visit_dates or []),
        field="available_visit_dates",
        kinds=VISIT,
        width=24,
    ),
    Column(
        "confirmed_visit_at",
        "확정 방문 일시",
        lambda p: _local(p.confirmed_visit_at),
        field="confirmed_visit_at",
        kinds=VISIT,
        width=17,
    ),
    Column("fee_requested", "희망 원고료", lambda p: p.fee_requested, field="fee_requested", internal=True, width=12),
    Column("fee_amount", "원고료", lambda p: p.fee_amount, field="fee_amount", width=12),
    Column("fee_currency", "통화", lambda p: p.fee_currency, field="fee_currency", kinds=SHIPPING, width=8),
    Column("payout_method", "송금 수단", lambda p: p.get_payout_method_display(), field="payout_method"),
    Column("payout_status", "지급 상태", lambda p: p.get_payout_status_display(), width=10),
    Column("paid_at", "지급일", lambda p: _local(p.paid_at), width=17),
    Column("carrier", "배송사", lambda p: p.carrier, field="carrier", kinds=SHIPPING, width=10),
    Column(
        "tracking_number", "송장번호", lambda p: p.tracking_number, field="tracking_number", kinds=SHIPPING, width=18
    ),
    Column("shipped_at", "발송일", lambda p: p.shipped_at, field="shipped_at", kinds=SHIPPING, width=11),
    Column("customs_issue", "통관 이슈", lambda p: p.customs_issue, field="customs_issue", kinds=SHIPPING, width=20),
    Column("received_at", "수령일", lambda p: p.received_at, field="received_at", kinds=SHIPPING, width=11),
    Column(
        "draft_submitted_at",
        "초안 제출일",
        lambda p: p.draft_submitted_at,
        field="draft_submitted_at",
        kinds=SHIPPING,
        width=11,
    ),
    Column(
        "revision_count", "수정 횟수", lambda p: p.revision_count, field="revision_count", kinds=SHIPPING, width=9
    ),
    Column(
        "upload_due_at", "업로드 기한", lambda p: _local(p.upload_due_at), field="upload_due_at", kinds=VISIT, width=17
    ),
    Column(
        "upload_planned_at",
        "업로드 예정일",
        lambda p: _local(p.upload_due_at),
        field="upload_due_at",
        kinds=SHIPPING,
        width=17,
    ),
    Column("upload_url", "업로드 URL", lambda p: p.upload_url, field="upload_url", width=36),
    Column("uploaded_at", "업로드 일시", lambda p: _local(p.uploaded_at), width=17),
    Column(
        "usage_rights_until",
        "2차 활용 종료일",
        lambda p: p.usage_rights_until,
        field="usage_rights_until",
        kinds=SHIPPING,
        width=13,
    ),
    Column(
        "ad_usage_allowed",
        "광고 집행 가능",
        lambda p: yes_no(p.ad_usage_allowed),
        field="ad_usage_allowed",
        kinds=SHIPPING,
        width=11,
    ),
    Column(
        "ad_code", "Spark Ads·화이트리스팅 코드", lambda p: p.ad_code, field="ad_code", kinds=SHIPPING, width=24
    ),
    Column(
        "disclosure_checked",
        "광고 표기 확인",
        lambda p: yes_no(p.disclosure_checked),
        field="disclosure_checked",
        kinds=SHIPPING,
        width=11,
    ),
    Column("special_notes", "특이사항", lambda p: p.special_notes, field="special_notes", width=30),
    Column(
        "last_contacted_at",
        "마지막 연락일",
        lambda p: p.last_contacted_at,
        field="last_contacted_at",
        internal=True,
        kinds=SHIPPING,
        width=12,
    ),
    Column(
        "next_action",
        "다음 할 일",
        lambda p: p.next_action,
        field="next_action",
        internal=True,
        kinds=SHIPPING,
        width=24,
    ),
    Column("email", "이메일", lambda p: p.influencer.email, internal=True, width=24),
    Column("survey_submitted_at", "설문 제출일", lambda p: _local(p.survey_submitted_at), internal=True, width=17),
    Column(
        "assignee",
        "담당자",
        lambda p: p.assignee.get_username() if p.assignee else "",
        field="assignee",
        internal=True,
        width=10,
    ),
    Column("notes", "비고", lambda p: p.notes, field="notes", internal=True, width=30),
]

SCOPE_CLIENT = "client"
SCOPE_INTERNAL = "internal"


def survey_columns(campaign):
    """구글 폼의 '추가 답변' 문항 -> 캠페인별 추가 열 (COLUMNS 뒤에 붙는다)."""
    from surveys.models import FormQuestion, Target

    questions = FormQuestion.objects.filter(form__campaign=campaign, is_active=True, target=Target.EXTRA)
    return [
        Column(
            f"form_{q.question_id}",
            q.title,
            lambda p, qid=q.question_id: (p.form_answers or {}).get(qid, ""),
            internal=not q.include_in_client_export,
            width=24,
        )
        for q in questions
    ]


def kind_columns(kind):
    """캠페인 유형(방문형/배송형)에 맞는 기본 열."""
    return [c for c in COLUMNS if not c.kinds or kind in c.kinds]


def campaign_columns(campaign):
    return kind_columns(campaign.kind) + survey_columns(campaign)


def client_only(columns):
    return [c for c in columns if not c.internal]


def columns_for(scope, campaign):
    columns = campaign_columns(campaign)
    return client_only(columns) if scope == SCOPE_CLIENT else columns


def display(value):
    """원본 값 -> 화면/CSV용 문자열."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return yes_no(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def display_screen(value):
    """화면 표시용: 숫자에 천 단위 구분 기호."""
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        return f"{value:,}"
    return display(value)
