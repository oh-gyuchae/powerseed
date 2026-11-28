"""Apify 클라우드 수집 — 녹스·PC 없이 플랫폼 서버에서 해시태그 → 계정 리스트.

웹 요청을 붙잡지 않도록 2단계 비동기로 돈다 (services.start_job → services.poll_job):
1) 해시태그 게시물 Actor 실행 → 게시물 작성자 계정을 모은다 (대표 게시물 조회수·좋아요·댓글)
2) 프로필 Actor 실행 → 팔로워·바이오·비즈니스 카테고리를 채운다
상태 확인은 수집 화면 자동 새로고침과 cron(`poll_collector_jobs`)이 한다.

입력/출력 키는 Apify 공개 Actor(apify/instagram-hashtag-scraper, apify/instagram-profile-scraper) 기준.
실제 토큰으로 처음 돌릴 때 결과 키가 맞는지 확인할 것 — 못 읽은 값은 비워 둔다.
"""

import httpx
from django.conf import settings

from influencers.models import normalize_handle

from . import CollectorError

BASE_URL = "https://api.apify.com/v2"
SUCCEEDED = "SUCCEEDED"
FAILED_STATES = {"FAILED", "ABORTED", "TIMED-OUT"}
POSTS_PER_ACCOUNT = 2  # 게시물 수 = 계정 수 × 2 (같은 계정 게시물이 겹치므로 넉넉히)


class ApifyClient:
    def __init__(self, http: httpx.Client | None = None):
        self._http = http

    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                base_url=BASE_URL, timeout=30, headers={"Authorization": f"Bearer {settings.APIFY_TOKEN}"}
            )
        return self._http

    @staticmethod
    def is_configured() -> bool:
        return bool(settings.APIFY_TOKEN)

    def _call(self, method, path, **kwargs):
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise CollectorError(f"Apify 연결 실패: {e}") from e
        if response.status_code >= 400:
            raise CollectorError(f"Apify 오류 {response.status_code}: {response.text[:200]}")
        try:
            return response.json()
        except ValueError as e:
            raise CollectorError("Apify 응답을 읽지 못했습니다.") from e

    def start(self, actor: str, payload: dict) -> str:
        """Actor 실행을 걸고 실행 ID를 돌려준다 (끝날 때까지 기다리지 않음)."""
        data = self._call("post", f"/acts/{actor}/runs", json=payload).get("data") or {}
        if not data.get("id"):
            raise CollectorError("Apify 실행 ID를 받지 못했습니다.")
        return data["id"]

    def run(self, run_id: str) -> dict:
        return self._call("get", f"/actor-runs/{run_id}").get("data") or {}

    def items(self, dataset_id: str) -> list[dict]:
        items = self._call("get", f"/datasets/{dataset_id}/items", params={"clean": "true", "format": "json"})
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return None


def hashtag_input(hashtag: str, limit: int) -> dict:
    return {"hashtags": [hashtag], "resultsLimit": limit * POSTS_PER_ACCOUNT}


def profile_input(handles: list[str]) -> dict:
    return {"usernames": handles}


def owners_from_posts(posts: list[dict], limit: int) -> list[dict]:
    """게시물 → 작성자 계정 (등장 순서 유지, 계정마다 조회수가 가장 높은 게시물을 대표로)."""
    by_handle: dict[str, dict] = {}
    for post in posts:
        handle = normalize_handle(str(post.get("ownerUsername") or ""))
        if not handle:
            continue
        views = _int(post.get("videoPlayCount")) or _int(post.get("videoViewCount"))
        row = by_handle.get(handle)
        if row is None:
            if len(by_handle) >= limit:
                continue
            row = by_handle[handle] = {
                "handle": handle,
                "account_name": str(post.get("ownerFullName") or "")[:100],
                "posts_found": 0,
                "views": None,
                "likes": None,
                "comments": None,
                "post_url": "",
            }
        row["posts_found"] += 1
        if row["post_url"] == "" or (views is not None and (row["views"] is None or views > row["views"])):
            row.update(
                views=views,
                likes=_int(post.get("likesCount")),
                comments=_int(post.get("commentsCount")),
                post_url=str(post.get("url") or "")[:200],
            )
    return list(by_handle.values())


def merge_profiles(accounts: list[dict], profiles: list[dict]) -> list[dict]:
    """계정 목록에 프로필 정보(팔로워·바이오 등)를 붙인다. 프로필을 못 받은 계정도 그대로 남긴다."""
    by_handle = {normalize_handle(str(p.get("username") or "")): p for p in profiles}
    merged = []
    for account in accounts:
        profile = by_handle.get(account["handle"], {})
        merged.append(
            {
                **account,
                "account_name": account.get("account_name") or str(profile.get("fullName") or "")[:100],
                "follower_count": _int(profile.get("followersCount")),
                "following": _int(profile.get("followsCount")),
                "media_count": _int(profile.get("postsCount")),
                "biography": str(profile.get("biography") or "")[:500],
                "business_category": str(profile.get("businessCategoryName") or "")[:100],
                "is_private": bool(profile.get("private")),
            }
        )
    return merged
