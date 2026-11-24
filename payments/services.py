"""참여 건 총비용(원화) 계산 — 정산 목록, 콘텐츠 성과(CPV·ROAS), 리포트가 같은 규칙을 쓴다.

총비용 = 지급 내역 원화 합계(수수료 포함) + 제품 원가 + 해외 배송비
지급 내역이 아직 없으면 확정(계약)된 건에 한해 원고료를 현재 환율로 환산해 대신 쓴다 (예상 비용).
환율표에 없는 통화는 합계에서 빠지고 `missing_rates`에 남는다.
"""

from .models import rate_for, to_krw


class CostBook:
    def __init__(self):
        self._rates = {}
        self.missing_rates = set()

    def rate(self, currency):
        if currency not in self._rates:
            self._rates[currency] = rate_for(currency)
        return self._rates[currency]

    def participation_cost(self, participation) -> int:
        """`participation.payments`는 prefetch_related("payments")로 미리 읽어 두면 쿼리가 늘지 않는다."""
        payments = list(participation.payments.all())
        if payments:
            fees = 0
            for payment in payments:
                if payment.cost_krw is None:
                    self.missing_rates.add(payment.currency)
                else:
                    fees += payment.cost_krw
        elif participation.fee_amount is not None and participation.is_committed:
            fees = to_krw(participation.fee_amount, self.rate(participation.fee_currency))
            if fees is None:
                self.missing_rates.add(participation.fee_currency)
                fees = 0
        else:
            fees = 0
        return fees + (participation.product_cost or 0) + (participation.shipping_cost or 0)
