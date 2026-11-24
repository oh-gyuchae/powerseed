"""시트 ① 인플루언서 DB 열 — 화면·엑셀·CSV 공용."""

from sheets.columns import Column, yes_no


def _rate(o):
    if o.desired_rate is None:
        return ""
    return f"{o.desired_rate:,} {o.desired_rate_currency}"


INFLUENCER_COLUMNS = [
    Column("instagram_handle", "계정(핸들)", lambda o: o.instagram_handle, width=20),
    Column("code", "인플루언서 ID", lambda o: o.code, width=11),
    Column("account_name", "계정 이름", lambda o: o.account_name),
    Column("platform", "플랫폼", lambda o: o.get_platform_display(), width=10),
    Column("country", "국가", lambda o: o.get_country_display(), width=10),
    Column("timezone", "시간대", lambda o: o.timezone, width=18),
    Column("languages", "사용 언어", lambda o: o.languages, width=14),
    Column("follower_count", "팔로워 수", lambda o: o.follower_count, width=11),
    Column("monthly_reels_avg", "평균 릴스 조회수", lambda o: o.monthly_reels_avg, width=13),
    Column("engagement_rate", "참여율(%)", lambda o: o.engagement_rate, width=9),
    Column("category", "카테고리", lambda o: o.get_category_display(), width=10),
    Column("audience_country", "주요 오디언스 국가", lambda o: o.get_audience_country_display(), width=14),
    Column("audience_gender", "오디언스 성별", lambda o: o.get_audience_gender_display(), width=11),
    Column("audience_age", "오디언스 연령", lambda o: o.audience_age, width=11),
    Column("email", "이메일", lambda o: o.email, width=24),
    Column("contact", "연락처", lambda o: o.contact, width=20),
    Column("agency", "에이전시", lambda o: o.agency or "소속 없음", width=14),
    Column("owner", "담당자", lambda o: o.owner.get_username() if o.owner else "", width=10),
    Column("desired_rate", "희망 단가", _rate, width=14),
    Column("campaign_count", "협업 이력(건)", lambda o: o.campaign_count, width=11),
    Column("is_blacklisted", "블랙리스트", lambda o: yes_no(o.is_blacklisted), width=9),
    Column("notes", "메모", lambda o: o.notes, width=30),
]
