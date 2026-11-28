"""참여 건 총비용(원화) 계산 — 콘텐츠 성과(CPV·CPM·ROAS), 리포트, 참여 상세가 같은 규칙을 쓴다.

총비용 = 확정 원고료(확정·계약된 건만) + 제품 원가 + 해외 배송비
정산(지급 내역·환율표)은 2026-11-28에 뺐다. 그래서 원화가 아닌 원고료는 환산할 수 없어 합계에서 빠지고
`missing_rates`에 통화가 남는다 (화면에 경고로 보여 준다).
"""

from core.choices import Currency


class CostBook:
    def __init__(self):
        self.missing_rates = set()

    def participation_cost(self, participation) -> int:
        fee = 0
        if participation.fee_amount is not None and participation.is_committed:
            if participation.fee_currency == Currency.KRW:
                fee = participation.fee_amount
            else:
                self.missing_rates.add(participation.fee_currency)
        return fee + (participation.product_cost or 0) + (participation.shipping_cost or 0)
