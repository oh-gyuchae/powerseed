"""수집기 어댑터 경계. 수집 도구가 바뀌어도 이 인터페이스만 맞추면 된다."""

from dataclasses import dataclass, field
from typing import Protocol


class CollectorError(Exception):
    """수집 실패. 메시지는 작업 화면에 그대로 표시된다."""


@dataclass
class CollectedAccount:
    handle: str
    account_name: str = ""
    account_url: str = ""
    follower_count: int | None = None
    raw: dict = field(default_factory=dict)


class CollectorAdapter(Protocol):
    def is_configured(self) -> bool: ...

    def collect(self, hashtag: str, limit: int) -> list[CollectedAccount]: ...


def get_adapter() -> CollectorAdapter:
    from .scraper import ScraperAdapter

    return ScraperAdapter()
