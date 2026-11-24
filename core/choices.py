"""여러 앱이 함께 쓰는 드롭다운 목록 (국가·통화).

표기가 섞이면 집계가 안 되므로 자유 입력 대신 이 목록만 쓴다. 항목 추가는 여기서만 한다.
"""

from django.db import models


class Country(models.TextChoices):
    KR = "KR", "한국"
    US = "US", "미국"
    CA = "CA", "캐나다"
    GB = "GB", "영국"
    FR = "FR", "프랑스"
    DE = "DE", "독일"
    ES = "ES", "스페인"
    IT = "IT", "이탈리아"
    JP = "JP", "일본"
    CN = "CN", "중국"
    TW = "TW", "대만"
    HK = "HK", "홍콩"
    TH = "TH", "태국"
    VN = "VN", "베트남"
    ID = "ID", "인도네시아"
    PH = "PH", "필리핀"
    MY = "MY", "말레이시아"
    SG = "SG", "싱가포르"
    AU = "AU", "호주"
    AE = "AE", "아랍에미리트"
    XX = "XX", "기타"


class Currency(models.TextChoices):
    KRW = "KRW", "KRW (원)"
    USD = "USD", "USD (달러)"
    JPY = "JPY", "JPY (엔)"
    EUR = "EUR", "EUR (유로)"
    GBP = "GBP", "GBP (파운드)"
    CNY = "CNY", "CNY (위안)"
    TWD = "TWD", "TWD (대만 달러)"
    HKD = "HKD", "HKD (홍콩 달러)"
    THB = "THB", "THB (바트)"
    VND = "VND", "VND (동)"
    IDR = "IDR", "IDR (루피아)"
    PHP = "PHP", "PHP (페소)"
    MYR = "MYR", "MYR (링깃)"
    SGD = "SGD", "SGD (싱가포르 달러)"
    AUD = "AUD", "AUD (호주 달러)"
    CAD = "CAD", "CAD (캐나다 달러)"
