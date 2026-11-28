"""수집한 계정의 카테고리(부문) 추정 — 해시태그 → 바이오·비즈니스 카테고리 순으로 키워드를 찾는다.

추정이라 틀릴 수 있다. 수집 작업에서 카테고리를 직접 고르면 그 값을 쓰고, 사람이 입력한 카테고리는 덮어쓰지 않는다.
"""

from influencers.models import Category

# 위에서부터 먼저 맞는 것을 쓴다 (예: '헤어메이크업'은 헤어보다 메이크업이 먼저 걸리지 않도록 헤어를 위에 둠).
KEYWORDS = [
    (Category.NAIL, ("네일", "nail", "젤네일")),
    (Category.HAIR, ("헤어", "hair", "미용실", "펌", "염색", "두피")),
    (Category.FRAGRANCE, ("향수", "perfume", "fragrance", "니치향")),
    (Category.MAKEUP, ("메이크업", "makeup", "화장", "립스틱", "쿠션", "아이섀도", "색조", "cosmetic")),
    (Category.SKINCARE, ("스킨케어", "skincare", "피부", "토너", "세럼", "앰플", "선크림", "수분크림", "skin")),
    (Category.BODY, ("바디", "body", "바디로션", "바디워시")),
    (Category.FASHION, ("패션", "fashion", "ootd", "코디", "데일리룩", "옷스타그램", "style")),
    (Category.FOOD, ("맛집", "먹스타그램", "카페", "디저트", "음식", "food", "foodie", "cafe", "베이커리", "레시피")),
    (Category.LIFESTYLE, ("일상", "육아", "인테리어", "여행", "lifestyle", "travel", "살림", "운동", "fitness")),
]


def guess_category(*texts: str) -> str:
    """앞에 준 글부터 차례로 본다. 못 찾으면 ''."""
    for text in texts:
        text = (text or "").lower()
        if not text:
            continue
        for category, words in KEYWORDS:
            if any(word in text for word in words):
                return category
    return ""
