"""insta-finder 결과 파일 올리기 (result.xlsx 또는 중간 CSV).

- xlsx: 시트 하나에 해시태그별 구역 — '#태그' 제목 줄 → 한국어 헤더 줄(계정|조회수|…) → 데이터 줄 → 빈 줄.
  맨 아래 '⚠️ 수집 실패 …' 줄에서 멈춘다.
- CSV: 영문 열 hashtag, username, views, likes, comments, shares, followers, following, posts,
  engagement_rate(%), views_per_follower.
조회수 등은 앱 표기('948K', '1.2만', '2,918') 그대로라 숫자로 바꿔 둔다. 못 읽은 값은 비운다.
"""

import csv
import io
import re

from openpyxl import load_workbook

from .adapters import CollectorError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

HEADER_KO = {
    "계정": "username",
    "조회수": "views",
    "좋아요": "likes",
    "댓글": "comments",
    "공유": "shares",
    "팔로워": "followers",
    "팔로잉": "following",
    "게시물수": "posts",
    "참여율(%)": "engagement_rate",
    "팔로워대비조회수": "views_per_follower",
    "계정 링크": "profile_link",
}
COUNT_FIELDS = ("views", "likes", "comments", "shares", "followers", "following", "posts")
UNITS = {"k": 1_000, "m": 1_000_000, "만": 10_000, "천": 1_000}
_COUNT_RE = re.compile(r"([\d.]+)\s*([KkMm만천]?)")


def to_count(value) -> int | None:
    """'948K'→948000, '1.2만'→12000, '2,918'→2918, 1234→1234. 못 읽으면 None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 else None
    match = _COUNT_RE.search(str(value).replace(",", ""))
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None
    return int(number * UNITS.get(match.group(2).lower(), 1))


def to_float(value) -> float | None:
    try:
        return round(float(str(value).replace(",", "")), 2) if value not in (None, "") else None
    except ValueError:
        return None


def _row(data: dict) -> dict | None:
    handle = str(data.get("username") or "").strip().lstrip("@")
    if not handle or handle.lower() == "nan":
        return None
    counts = {key: to_count(data.get(key)) for key in COUNT_FIELDS}
    return {
        "handle": handle,
        "follower_count": counts.pop("followers"),
        "media_count": counts.pop("posts"),
        **counts,
        "engagement_rate": to_float(data.get("engagement_rate") or data.get("engagement_rate(%)")),
        "views_per_follower": to_float(data.get("views_per_follower")),
        "source_file": "insta-finder",
    }


def parse_csv(content: bytes) -> dict[str, list[dict]]:
    text = content.decode("utf-8-sig", errors="replace")
    groups: dict[str, list[dict]] = {}
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "username" not in reader.fieldnames or "hashtag" not in reader.fieldnames:
        raise CollectorError("CSV에 hashtag, username 열이 없습니다. insta-finder의 결과 CSV인지 확인하세요.")
    for data in reader:
        row = _row(data)
        if row:
            groups.setdefault(str(data.get("hashtag") or "").strip(), []).append(row)
    return groups


def parse_xlsx(content: bytes) -> dict[str, list[dict]]:
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as e:
        raise CollectorError("엑셀 파일을 열지 못했습니다.") from e
    groups: dict[str, list[dict]] = {}
    tag, header = None, None
    for values in workbook.active.iter_rows(values_only=True):
        cells = ["" if v is None else v for v in values]
        first = str(cells[0]).strip() if cells else ""
        if not any(str(c).strip() for c in cells):
            continue
        if first.startswith("⚠"):
            break
        if first.startswith("#") and not any(str(c).strip() for c in cells[1:]):
            tag, header = first, None
            continue
        if first == "계정":
            header = [HEADER_KO.get(str(c).strip(), "") for c in cells]
            continue
        if tag and header:
            row = _row({key: value for key, value in zip(header, cells, strict=False) if key})
            if row:
                groups.setdefault(tag, []).append(row)
    workbook.close()
    if not groups:
        raise CollectorError("엑셀에서 '#해시태그' 구역과 '계정' 헤더를 찾지 못했습니다. insta-finder의 result.xlsx인지 확인하세요.")
    return groups


def parse_upload(uploaded) -> dict[str, list[dict]]:
    """{'#해시태그': [계정 dict, ...]} — 해시태그 정규화는 호출하는 쪽에서."""
    if uploaded.size > MAX_UPLOAD_BYTES:
        raise CollectorError("파일이 너무 큽니다 (5MB까지).")
    content = uploaded.read()
    name = (uploaded.name or "").lower()
    if name.endswith(".csv"):
        return parse_csv(content)
    if name.endswith(".xlsx"):
        return parse_xlsx(content)
    raise CollectorError("xlsx 또는 csv 파일만 올릴 수 있습니다.")
