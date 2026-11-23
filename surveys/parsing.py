"""구글 폼 답변(자유 입력 문자열) -> 플랫폼 값 변환. 인식 못 하면 None을 돌려주고 원래 값은 건드리지 않는다."""

import datetime
import re

from campaigns.models import Participation

from .models import Target

_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(만|천|k|m)?", re.IGNORECASE)
_UNIT = {"만": 10_000, "천": 1_000, "k": 1_000, "m": 1_000_000}


def parse_amount(text):
    """'10만원' -> 100000, '1.5만' -> 15000, '120,000' -> 120000, '12k' -> 12000, '협의' -> None."""
    text = (text or "").replace(",", "").strip()
    match = _AMOUNT_RE.search(text)
    if not match:
        return None
    number = float(match.group(1)) * _UNIT.get((match.group(2) or "").lower(), 1)
    return int(round(number))


def parse_dates(values, *, year):
    """['2026-12-01', '12/3', '12월 5일'] -> ['2026-12-01', '2026-12-03', '2026-12-05'] (인식 못 한 값은 건너뜀)."""
    found = set()
    for value in values:
        for part in re.split(r"[,\n·]", value):
            parsed = _parse_one_date(part.strip(), year)
            if parsed:
                found.add(parsed.isoformat())
    return sorted(found)


def _parse_one_date(text, year):
    if not text:
        return None
    patterns = [
        (r"(\d{4})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})", lambda m: (int(m[1]), int(m[2]), int(m[3]))),
        (r"(\d{1,2})\s*[-./월]\s*(\d{1,2})", lambda m: (year, int(m[1]), int(m[2]))),
    ]
    for pattern, build in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return datetime.date(*build(match))
            except ValueError:
                return None
    return None


def parse_participation_status(text):
    text = (text or "").strip().lower()
    if not text:
        return None
    Status = Participation.ParticipationStatus
    if any(w in text for w in ("불참", "불가", "아니", "못", "어렵", "어려", "no")):
        return Status.NO
    if any(w in text for w in ("검토", "고민", "미정", "보류", "모르")):
        return Status.CONSIDERING
    if any(w in text for w in ("참여", "참가", "가능", "예", "네", "yes", "좋")):
        return Status.YES
    return None


def parse_payout_method(text):
    text = (text or "").strip().lower()
    if not text:
        return None
    Method = Participation.PayoutMethod
    for words, method in [
        (("세금계산서", "사업자"), Method.TAX_INVOICE),
        (("계좌", "이체", "입금"), Method.BANK_TRANSFER),
        (("페이팔", "paypal"), Method.PAYPAL),
        (("제품", "무료", "협찬"), Method.PRODUCT_ONLY),
    ]:
        if any(w in text for w in words):
            return method
    return Method.OTHER


# 질문 제목 -> 옮겨 적을 칸 자동 추정. 위에서부터 처음 맞는 규칙을 쓴다.
_GUESS_RULES = [
    (("참여 코드", "참여코드", "응답 코드"), Target.PARTICIPATION_CODE),
    (("방문", "날짜", "일정"), Target.AVAILABLE_VISIT_DATES),
    (("성함", "이름", "닉네임", "계정명"), Target.ACCOUNT_NAME),
    (("이메일", "메일", "email"), Target.EMAIL),
    (("팔로워",), Target.FOLLOWER_COUNT),
    (("릴스", "조회수"), Target.MONTHLY_REELS_AVG),
    (("원고료", "단가", "비용", "금액"), Target.FEE_REQUESTED),
    (("송금", "정산", "지급", "입금"), Target.PAYOUT_METHOD),
    (("참여",), Target.PARTICIPATION_STATUS),
    (("인스타", "instagram", "계정", "아이디"), Target.INSTAGRAM_HANDLE),
    (("특이", "비고", "요청", "문의"), Target.SPECIAL_NOTES),
]


def guess_target(title):
    lowered = (title or "").lower()
    for words, target in _GUESS_RULES:
        if any(w in lowered for w in words):
            return target
    return Target.EXTRA
