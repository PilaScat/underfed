from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

from .constants import (
    API_KEY_ENV,
    DEFAULT_API_URL,
    DEFAULT_CONFIRM_SECONDS,
    DEFAULT_MAX_SWITCHES_PER_HOUR,
    DEFAULT_RATIO_PERCENT,
    DEFAULT_STABLE_SECONDS,
    DEFAULT_TELEMETRY_PATH,
    DEFAULT_WARMUP_SECONDS,
    MAPPING_REFRESH_SECONDS,
    MAX_RECENT_EVENTS,
    POLL_INTERVAL_SECONDS,
)
from .detector import Detector, Thresholds, Verdict
from .dispatcharr import ApiError, Catalogue, Client
from .journal import Journal
from .tailer import Tailer

STATUS_REFRESH_SECONDS = 5.0
CATALOGUE_RETRY_SECONDS = 60.0


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="underfed")
    parser.add_argument("--telemetry", default=DEFAULT_TELEMETRY_PATH)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--ratio-percent", type=float, default=DEFAULT_RATIO_PERCENT)
    parser.add_argument("--confirm-seconds", type=float, default=DEFAULT_CONFIRM_SECONDS)
    parser.add_argument("--warmup-seconds", type=float, default=DEFAULT_WARMUP_SECONDS)
    parser.add_argument("--stable-seconds", type=float, default=DEFAULT_STABLE_SECONDS)
    parser.add_argument("--max-switches", type=int, default=DEFAULT_MAX_SWITCHES_PER_HOUR)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--observe-only", action="store_true")
    return parser.parse_args(argv)


class Watcher:
    def __init__(self, options: argparse.Namespace, client: Client) -> None:
        self.options = options
        self.client = client
        self.detector = Detector(
            Thresholds(
                ratio=min(max(options.ratio_percent, 1.0), 99.0) / 100,
                confirm_seconds=max(options.confirm_seconds, 5.0),
                warmup_seconds=max(options.warmup_seconds, 0.0),
                stable_seconds=max(options.stable_seconds, 0.0),
            )
        )
        self.journal = Journal(Path(options.journal), MAX_RECENT_EVENTS)
        self.tailer = Tailer(Path(options.telemetry))
        self.excluded = {value.strip().casefold() for value in options.exclude if value.strip()}
        self.catalogue = Catalogue()
        self.active: dict[str, object] = {}
        self.switches: dict[str, deque[float]] = defaultdict(deque)
        self._catalogue_at = 0.0
        self._status_at = 0.0
        self._running = True

    def stop(self, *_: object) -> None:
        self._running = False

    def run(self) -> int:
        self.journal.write(
            "started",
            observe_only=bool(self.options.observe_only),
            telemetry=str(self.options.telemetry),
            ratio_percent=self.options.ratio_percent,
            confirm_seconds=self.options.confirm_seconds,
        )
        while self._running:
            self._refresh()
            for line in self.tailer.read():
                self._consume(line)
            time.sleep(POLL_INTERVAL_SECONDS)
        self.journal.write("stopped")
        return 0

    def _refresh(self) -> None:
        now = time.monotonic()
        if now - self._status_at >= STATUS_REFRESH_SECONDS:
            self._status_at = now
            try:
                self.active = dict(self.client.active())
            except ApiError as error:
                self.journal.write("api_error", where="status", detail=str(error))
        if now - self._catalogue_at >= MAPPING_REFRESH_SECONDS:
            self._catalogue_at = now
            try:
                self.catalogue = self.client.catalogue()
            except ApiError as error:
                self._catalogue_at = now - MAPPING_REFRESH_SECONDS + CATALOGUE_RETRY_SECONDS
                self.journal.write("api_error", where="catalogue", detail=str(error))

    def _consume(self, line: str) -> None:
        from .telemetry import parse

        sample = parse(line)
        if sample is None:
            return
        verdict = self.detector.observe(sample)
        if verdict is not None:
            self._act(verdict)

    def _act(self, verdict: Verdict) -> None:
        channel = self.active.get(verdict.feed)
        if channel is None:
            self.journal.write("skipped", reason="channel not streaming", **self._facts(verdict))
            return
        if getattr(channel, "clients", 0) <= 0:
            self.journal.write("skipped", reason="no clients", **self._facts(verdict))
            return

        uuid = getattr(channel, "uuid", "")
        name = getattr(channel, "name", "") or uuid
        if self._is_excluded(name):
            self.journal.write("skipped", reason="excluded", channel=name, **self._facts(verdict))
            return

        if self._too_many(uuid):
            self.journal.write(
                "skipped", reason="switch limit reached", channel=name, **self._facts(verdict)
            )
            return

        following = self.catalogue.next_entry(uuid, verdict.feed)
        if following is None:
            self.journal.write(
                "skipped", reason="no source after this one", channel=name, **self._facts(verdict)
            )
            return
        if following.is_slate:
            self.journal.write(
                "skipped", reason="next source is the slate", channel=name, **self._facts(verdict)
            )
            return

        if self.options.observe_only:
            self.journal.write(
                "would_switch", channel=name, to=following.name, **self._facts(verdict)
            )
            return

        try:
            self.client.next_stream(uuid)
        except ApiError as error:
            self.journal.write(
                "failed", channel=name, detail=str(error), **self._facts(verdict)
            )
            return

        self.switches[uuid].append(time.time())
        self.active.pop(verdict.feed, None)
        self._status_at = 0.0
        self.journal.write("switched", channel=name, to=following.name, **self._facts(verdict))

    def _facts(self, verdict: Verdict) -> dict:
        return {
            "feed": verdict.feed,
            "percent": verdict.percent,
            "in_mbps": round(verdict.in_mbps, 2),
            "crate_mbps": round(verdict.crate_mbps, 2),
            "starving_seconds": round(verdict.seconds),
        }

    def _is_excluded(self, name: str) -> bool:
        return name.strip().casefold() in self.excluded

    def _too_many(self, uuid: str) -> bool:
        recent = self.switches[uuid]
        cutoff = time.time() - 3600
        while recent and recent[0] < cutoff:
            recent.popleft()
        return len(recent) >= max(self.options.max_switches, 0)


def main(argv: list[str] | None = None) -> int:
    options = arguments(argv)
    key = os.environ.get(API_KEY_ENV, "")
    if not key:
        print(f"{API_KEY_ENV} is not set", file=sys.stderr)
        return 2
    watcher = Watcher(options, Client(options.api_url, key))
    for name in ("SIGTERM", "SIGINT"):
        number = getattr(signal, name, None)
        if number is not None:
            signal.signal(number, watcher.stop)
    return watcher.run()


if __name__ == "__main__":
    raise SystemExit(main())
