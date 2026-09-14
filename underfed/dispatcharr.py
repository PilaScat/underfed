from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .constants import API_TIMEOUT_SECONDS, PLUGIN_VERSION


class ApiError(RuntimeError):
    pass


def feed_of(url: object) -> str:
    path = urllib.parse.urlparse(str(url or "")).path
    return path.rsplit("/", 1)[-1]


def local_path(url: object) -> str:
    if not url:
        return ""
    parts = urllib.parse.urlparse(str(url))
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


@dataclass(frozen=True)
class ActiveChannel:
    uuid: str
    name: str
    feed: str
    clients: int


@dataclass(frozen=True)
class ChainEntry:
    stream_id: int
    feed: str
    name: str
    is_slate: bool


@dataclass
class Catalogue:
    chains: dict[str, list[ChainEntry]] = field(default_factory=dict)
    numeric_ids: dict[str, int] = field(default_factory=dict)

    def next_entry(self, uuid: str, current_feed: str) -> ChainEntry | None:
        chain = self.chains.get(uuid) or []
        for index, entry in enumerate(chain):
            if entry.feed == current_feed:
                return chain[index + 1] if index + 1 < len(chain) else None
        return None


class Client:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _request(self, path: str, method: str = "GET") -> object:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method=method,
            headers={
                "X-API-Key": self.api_key,
                "Accept": "application/json",
                "User-Agent": f"underfed/{PLUGIN_VERSION}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            raise ApiError(f"{method} {path} returned {error.code}") from error
        except (urllib.error.URLError, OSError) as error:
            raise ApiError(f"{method} {path} failed: {error}") from error
        if not body:
            return {}
        try:
            return json.loads(body)
        except ValueError as error:
            raise ApiError(f"{method} {path} returned invalid JSON") from error

    def active(self) -> dict[str, ActiveChannel]:
        payload = self._request("/proxy/ts/status")
        rows = payload.get("channels", []) if isinstance(payload, dict) else []
        found: dict[str, ActiveChannel] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            feed = feed_of(row.get("url"))
            if not feed:
                continue
            found[feed] = ActiveChannel(
                uuid=str(row.get("channel_id") or ""),
                name=str(row.get("channel_name") or ""),
                feed=feed,
                clients=int(row.get("client_count") or 0),
            )
        return found

    def catalogue(self) -> Catalogue:
        streams = self._collect("/api/channels/streams/?page_size=9000")
        details = {}
        for row in streams:
            identifier = row.get("id")
            if identifier is None:
                continue
            url = str(row.get("url") or "")
            details[int(identifier)] = ChainEntry(
                stream_id=int(identifier),
                feed=feed_of(url),
                name=str(row.get("name") or ""),
                is_slate="slate" in url or "127.0.0.1" in url,
            )

        catalogue = Catalogue()
        for row in self._collect("/api/channels/channels/?page_size=500"):
            uuid = str(row.get("uuid") or "")
            if not uuid:
                continue
            chain = [details[int(i)] for i in (row.get("streams") or []) if int(i) in details]
            catalogue.chains[uuid] = chain
            if row.get("id") is not None:
                catalogue.numeric_ids[uuid] = int(row["id"])
        return catalogue

    def _collect(self, path: str) -> list[dict]:
        rows: list[dict] = []
        requested: set[str] = set()
        while path and path not in requested:
            requested.add(path)
            payload = self._request(path)
            if isinstance(payload, list):
                page, path = payload, ""
            elif isinstance(payload, dict):
                page, path = payload.get("results") or [], local_path(payload.get("next"))
            else:
                break
            rows.extend(row for row in page if isinstance(row, dict))
        return rows

    def next_stream(self, uuid: str) -> None:
        self._request(f"/proxy/ts/next_stream/{uuid}", method="POST")
