"""기존 Python 스크래퍼를 감싸는 어댑터.

`COLLECTOR_SCRAPER`에 호출 경로를 지정한다 (예: collector.vendor.scraper.collect).
호출 형식: `collect(hashtag: str, limit: int) -> Iterable[dict]`
dict 키: handle(또는 username), account_name, account_url, follower_count
"""

import json
import logging
import time
from itertools import islice

from django.conf import settings
from django.utils.module_loading import import_string

from . import CollectedAccount, CollectorError

logger = logging.getLogger(__name__)
MAX_FOLLOWERS = 2_147_483_647  # PositiveIntegerField 상한


def parse_followers(value) -> int | None:
    """정수 또는 '12,300' 형식만 읽는다. 읽지 못하면 None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        value = value.replace(",", "").strip()
        if not value.isascii() or not value.isdigit():
            return None
    elif not isinstance(value, int):
        return None
    number = int(value)
    return number if 0 <= number <= MAX_FOLLOWERS else None


def _clean_url(value) -> str:
    value = str(value or "").strip()
    return value if value.startswith(("https://", "http://")) and len(value) <= 200 else ""


def _json_safe(row: dict) -> dict:
    return json.loads(json.dumps(row, ensure_ascii=False, default=str))


def to_account(row: dict) -> CollectedAccount:
    return CollectedAccount(
        handle=str(row.get("handle") or row.get("username") or ""),
        account_name=str(row.get("account_name") or "")[:100],
        account_url=_clean_url(row.get("account_url")),
        follower_count=parse_followers(row.get("follower_count")),
        raw=_json_safe(row),
    )


class ScraperAdapter:
    def is_configured(self) -> bool:
        return bool(settings.COLLECTOR_SCRAPER)

    def collect(self, hashtag: str, limit: int) -> list[CollectedAccount]:
        if not self.is_configured():
            raise CollectorError("수집기가 연결되지 않았습니다. .env의 COLLECTOR_SCRAPER를 설정하세요.")
        try:
            scrape = import_string(settings.COLLECTOR_SCRAPER)
        except ImportError as e:
            raise CollectorError(f"수집기를 불러오지 못했습니다: {e}") from e

        attempts = max(1, settings.COLLECTOR_MAX_ATTEMPTS)
        for attempt in range(1, attempts + 1):
            try:
                rows = list(islice(scrape(hashtag, limit), limit))
                return [to_account(row) for row in rows]
            except Exception as e:
                logger.warning("수집 실패 #%s (%s/%s): %s", hashtag, attempt, attempts, e)
                if attempt == attempts:
                    raise CollectorError(f"{attempts}회 시도 후 실패: {e}") from e
                time.sleep(settings.COLLECTOR_RETRY_DELAY)
        raise CollectorError("수집 실패")  # pragma: no cover
