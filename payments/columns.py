"""시트 ④ 정산 열 — 화면·엑셀·CSV 공용. 정산은 사내 전용이므로 고객사용 구분이 없다."""

from sheets.columns import Column, yes_no

PAYMENT_COLUMNS = [
    Column("influencer", "인스타 계정", lambda o: o.participation.influencer.instagram_handle, width=20),
    Column("code", "인플루언서 ID", lambda o: o.participation.influencer.code, width=11),
    Column("campaign", "캠페인", lambda o: o.participation.campaign.name, width=20),
    Column("installment", "구분", lambda o: o.get_installment_display(), width=7),
    Column("amount", "금액", lambda o: o.amount, width=12),
    Column("currency", "통화", lambda o: o.currency, width=7),
    Column("fx_rate", "적용 환율", lambda o: o.fx_rate, width=10),
    Column("amount_krw", "원화 환산액", lambda o: o.amount_krw, width=13),
    Column("method", "지급 방법", lambda o: o.get_method_display(), width=10),
    Column("fee", "수수료", lambda o: o.fee, width=9),
    Column("fee_krw", "수수료(원)", lambda o: o.fee_krw, width=10),
    Column("tax_document", "세금 서류", lambda o: o.get_tax_document_display(), width=9),
    Column("tax_document_received", "세금 서류 수령", lambda o: yes_no(o.tax_document_received), width=11),
    Column("invoice_received", "인보이스 수령", lambda o: yes_no(o.invoice_received), width=11),
    Column("status", "지급 상태", lambda o: o.status_label, width=12),
    Column("paid_at", "지급일", lambda o: o.paid_at, width=11),
    Column("notes", "메모", lambda o: o.notes, width=24),
]
