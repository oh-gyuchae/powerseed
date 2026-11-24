"""시트 ③ 콘텐츠 성과 열 — 화면·엑셀·CSV 공용. 행 객체는 selectors.with_metrics()가 계산 열을 붙인 ContentPost."""

from sheets.columns import Column

POST_COLUMNS = [
    Column("influencer", "인스타 계정", lambda o: o.participation.influencer.instagram_handle, width=20),
    Column("code", "인플루언서 ID", lambda o: o.participation.influencer.code, width=11),
    Column("campaign", "캠페인", lambda o: o.participation.campaign.name, width=20),
    Column("url", "게시물 URL", lambda o: o.url, width=36),
    Column("posted_at", "업로드일", lambda o: o.posted_at, width=11),
    Column("format", "형식", lambda o: o.get_format_display(), width=9),
    Column("views_d7", "조회수(7일)", lambda o: o.views_d7, width=11),
    Column("likes_d7", "좋아요(7일)", lambda o: o.likes_d7, width=10),
    Column("comments_d7", "댓글(7일)", lambda o: o.comments_d7, width=9),
    Column("saves_d7", "저장(7일)", lambda o: o.saves_d7, width=9),
    Column("shares_d7", "공유(7일)", lambda o: o.shares_d7, width=9),
    Column("views_d30", "조회수(30일)", lambda o: o.views_d30, width=11),
    Column("likes_d30", "좋아요(30일)", lambda o: o.likes_d30, width=10),
    Column("comments_d30", "댓글(30일)", lambda o: o.comments_d30, width=9),
    Column("saves_d30", "저장(30일)", lambda o: o.saves_d30, width=9),
    Column("shares_d30", "공유(30일)", lambda o: o.shares_d30, width=9),
    Column("discount_code_uses", "할인코드 사용", lambda o: o.discount_code_uses, width=11),
    Column("link_clicks", "링크 클릭(UTM)", lambda o: o.link_clicks, width=11),
    Column("revenue", "매출(원)", lambda o: o.revenue, width=12),
    Column("engagement_rate", "참여율(%)", lambda o: o.engagement_rate, width=9),
    Column("cost_krw", "배분 비용(원)", lambda o: o.cost_krw, internal=True, width=12),
    Column("cpv", "CPV(원)", lambda o: o.cpv, internal=True, width=9),
    Column("cpm", "CPM(원)", lambda o: o.cpm, internal=True, width=10),
    Column("roas", "ROAS(%)", lambda o: o.roas, internal=True, width=9),
    Column("notes", "메모", lambda o: o.notes, internal=True, width=24),
]
