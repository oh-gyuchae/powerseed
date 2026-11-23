"""캠페인 시트 열 정의 — 화면 표·CSV·엑셀 내보내기가 모두 이 목록 하나를 쓴다.

열을 추가/삭제/순서 변경하려면 COLUMNS만 고치면 된다.
- `internal=True` 열은 사내용 내보내기에만 들어가고, 고객사 전달용 파일에서는 빠진다.
- `field`가 있는 열은 시트 화면에서 바로 수정할 수 있다 (ParticipationForm / stage 필드 이름).
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from django.utils import timezone


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    get: Callable[[Any], Any]  # Participation -> 원본 값 (int / str / datetime / None)
    field: str | None = None
    internal: bool = False
    width: int = 14  # 엑셀 열 너비


def _local(dt):
    return timezone.localtime(dt) if dt else None


COLUMNS = [
    Column("instagram_handle", "인스타 계정", lambda p: p.influencer.instagram_handle, width=20),
    Column("account_name", "계정 이름", lambda p: p.influencer.account_name),
    Column("platform", "플랫폼", lambda p: p.influencer.get_platform_display(), width=10),
    Column("account_url", "계정 URL", lambda p: p.influencer.account_url, width=36),
    Column("follower_count", "팔로워 수", lambda p: p.influencer.follower_count, width=11),
    Column("monthly_reels_avg", "한 달 릴스 평균", lambda p: p.influencer.monthly_reels_avg, width=13),
    Column("stage", "진행 단계", lambda p: p.get_stage_display(), field="stage", width=12),
    Column(
        "participation_status",
        "참여 의사",
        lambda p: p.get_participation_status_display(),
        field="participation_status",
        width=10,
    ),
    Column(
        "available_visit_dates",
        "방문 가능일",
        lambda p: ", ".join(p.available_visit_dates or []),
        field="available_visit_dates",
        width=24,
    ),
    Column(
        "confirmed_visit_at", "확정 방문 일시", lambda p: _local(p.confirmed_visit_at), field="confirmed_visit_at", width=17
    ),
    Column("fee_requested", "희망 원고료", lambda p: p.fee_requested, field="fee_requested", internal=True, width=12),
    Column("fee_amount", "원고료", lambda p: p.fee_amount, field="fee_amount", width=12),
    Column("payout_method", "송금 수단", lambda p: p.get_payout_method_display(), field="payout_method"),
    Column("payout_status", "지급 상태", lambda p: p.get_payout_status_display(), width=10),
    Column("paid_at", "지급일", lambda p: _local(p.paid_at), width=17),
    Column("upload_due_at", "업로드 기한", lambda p: _local(p.upload_due_at), field="upload_due_at", width=17),
    Column("upload_url", "업로드 URL", lambda p: p.upload_url, field="upload_url", width=36),
    Column("uploaded_at", "업로드 일시", lambda p: _local(p.uploaded_at), width=17),
    Column("special_notes", "특이사항", lambda p: p.special_notes, field="special_notes", width=30),
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


def campaign_columns(campaign):
    return COLUMNS + survey_columns(campaign)


def columns_for(scope, campaign=None):
    columns = campaign_columns(campaign) if campaign is not None else list(COLUMNS)
    if scope == SCOPE_CLIENT:
        return [c for c in columns if not c.internal]
    return columns


def display(value):
    """원본 값 -> 화면/CSV용 문자열."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def display_screen(value):
    """화면 표시용: 숫자에 천 단위 구분 기호."""
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return display(value)
