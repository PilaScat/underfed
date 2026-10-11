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
    CAUSE_EMPTY,
    CAUSE_FORBIDDEN,
    CAUSE_TIMESTAMPS,
    CAUSE_UNDERFED,
    DEFAULT_API_URL,
    DEFAULT_CONFIRM_SECONDS,
    DEFAULT_DEMOTE_MINUTES,
    DEFAULT_MAX_SWITCHES_PER_HOUR,
    DEFAULT_RATIO_PERCENT,
    DEFAULT_STABLE_SECONDS,
    DEFAULT_STORM_CONFIRM_SECONDS,
    DEFAULT_STORM_PER_MINUTE,
    DEFAULT_TELEMETRY_PATH,
    DEFAULT_WARMUP_SECONDS,
    MAPPING_REFRESH_SECONDS,
    MAX_RECENT_EVENTS,
    POLL_INTERVAL_SECONDS,
)
from .demotions import Demotion, demoted_order, position_of, restored_order
from .detector import Detector, Thresholds, Verdict
from .dispatcharr import ApiError, Catalogue, ChainEntry, Client
from .empty import EmptySourceTracker
from .forbidden import parse_refusal
from .journal import Journal
from .state import load, save
from .storm import Storm, StormDetector
from .tailer import Tailer

STATUS_REFRESH_SECONDS = 5.0
CATALOGUE_RETRY_SECONDS = 60.0
HOUR_SECONDS = 3600.0
SWITCHES_FILE = "switches.json"
DEMOTIONS_FILE = "demotions.json"


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
    parser.add_argument("--storm-per-minute", type=int, default=DEFAULT_STORM_PER_MINUTE)
    parser.add_argument(
        "--storm-confirm-seconds", type=float, default=DEFAULT_STORM_CONFIRM_SECONDS
    )
    parser.add_argument("--demote-minutes", type=float, default=DEFAULT_DEMOTE_MINUTES)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--observe-only", action="store_true")
    return parser.parse_args(argv)


class Watcher:
    def __init__(self, options: argparse.Namespace, client: Client) -> None:
        self.options = options
        self.client = client
        thresholds = Thresholds(
            ratio=min(max(options.ratio_percent, 1.0), 99.0) / 100,
            confirm_seconds=max(options.confirm_seconds, 5.0),
            warmup_seconds=max(options.warmup_seconds, 0.0),
            stable_seconds=max(options.stable_seconds, 0.0),
            storm_per_minute=max(options.storm_per_minute, 0),
            storm_confirm_seconds=max(options.storm_confirm_seconds, 5.0),
        )
        self.detector = Detector(thresholds)
        self.storms = StormDetector(thresholds)
        self.empty_sources = EmptySourceTracker()
        self.journal = Journal(Path(options.journal), MAX_RECENT_EVENTS)
        self.tailer = Tailer(Path(options.telemetry))
        self.excluded = {value.strip().casefold() for value in options.exclude if value.strip()}
        self.catalogue = Catalogue()
        self.active: dict[str, object] = {}
        self.switches_path = Path(options.journal).with_name(SWITCHES_FILE)
        self.switches: dict[str, deque[float]] = defaultdict(deque, self._recall_switches())
        self.demotions_path = Path(options.journal).with_name(DEMOTIONS_FILE)
        self.demotions: list[Demotion] = self._recall_demotions()
        self._catalogue_at = float("-inf")
        self._status_at = float("-inf")
        self._last_error = ""
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
            storm_per_minute=self.options.storm_per_minute,
            storm_confirm_seconds=self.options.storm_confirm_seconds,
        )
        while self._running:
            self.step()
            time.sleep(POLL_INTERVAL_SECONDS)
        self.journal.write("stopped")
        return 0

    def step(self) -> None:
        try:
            self._refresh()
            self._restore_due()
            for line in self.tailer.read():
                self._consume(line)
        except Exception as error:
            detail = f"{type(error).__name__}: {error}"
            if detail != self._last_error:
                self.journal.write("error", detail=detail)
            self._last_error = detail

    def _restore_due(self) -> None:
        now = time.time()
        due = [row for row in self.demotions if row.until <= now]
        if not due:
            return
        try:
            self.catalogue = self.client.catalogue()
            self._catalogue_at = time.monotonic()
        except ApiError as error:
            self.journal.write("api_error", where="catalogue", detail=str(error))
            return
        for row in due:
            self.demotions.remove(row)
            chain = self.catalogue.chains.get(row.uuid) or []
            channel_id = self.catalogue.numeric_ids.get(row.uuid)
            order = restored_order(chain, row.stream_id, row.position)
            if channel_id is not None and order is not None:
                try:
                    self.client.set_chain(channel_id, order)
                    self.journal.write("restored", feed=row.feed, position=row.position)
                except ApiError as error:
                    self.journal.write("failed", feed=row.feed, detail=str(error))
        self._keep_demotions()

    def _demote(self, feed: str, cause: str) -> None:
        if self.options.demote_minutes <= 0:
            return
        if any(row.feed == feed for row in self.demotions):
            return
        channel = self.active.get(feed)
        uuid = getattr(channel, "uuid", "") if channel else ""
        if not uuid:
            return
        chain = self.catalogue.chains.get(uuid) or []
        entry = next((row for row in chain if row.feed == feed), None)
        channel_id = self.catalogue.numeric_ids.get(uuid)
        if entry is None or channel_id is None:
            return
        position = position_of(chain, entry.stream_id)
        order = demoted_order(chain, entry.stream_id)
        name = getattr(channel, "name", "") or uuid
        if order is None or position is None:
            self.journal.write("skipped", cause=cause, channel=name, feed=feed,
                               reason="nowhere lower to go")
            return
        if self.options.observe_only:
            self.journal.write("would_demote", cause=cause, channel=name, feed=feed,
                               minutes=self.options.demote_minutes)
            return
        try:
            self.client.set_chain(channel_id, order)
        except ApiError as error:
            self.journal.write("failed", cause=cause, channel=name, feed=feed,
                               detail=str(error))
            return
        until = time.time() + self.options.demote_minutes * 60
        self.demotions.append(
            Demotion(
                uuid=uuid,
                stream_id=entry.stream_id,
                feed=feed,
                position=position,
                until=until,
            )
        )
        self._keep_demotions()
        self.journal.write("demoted", cause=cause, channel=name, feed=feed,
                           position=position, minutes=self.options.demote_minutes)

    def _recall_demotions(self) -> list[Demotion]:
        stored = load(self.demotions_path).get("demotions")
        rows: list[Demotion] = []
        if not isinstance(stored, list):
            return rows
        for row in stored:
            if not isinstance(row, dict):
                continue
            try:
                rows.append(
                    Demotion(
                        uuid=str(row["uuid"]),
                        stream_id=int(row["stream_id"]),
                        feed=str(row["feed"]),
                        position=int(row["position"]),
                        until=float(row["until"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return rows

    def _keep_demotions(self) -> None:
        save(
            self.demotions_path,
            {"demotions": [vars(row) for row in self.demotions]},
        )

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
        from .telemetry import parse, parse_discontinuity

        refusal = parse_refusal(line)
        if refusal is not None:
            self._demote(refusal.feed, CAUSE_FORBIDDEN)
            return
        empty = self.empty_sources.observe(line)
        if empty is not None:
            self._demote(empty.feed, CAUSE_EMPTY)
            return
        sample = parse(line)
        if sample is not None:
            verdict = self.detector.observe(sample)
            if verdict is not None:
                self._act(verdict.feed, self._facts(verdict))
            return
        jump = parse_discontinuity(line)
        if jump is not None:
            storm = self.storms.observe(jump)
            if storm is not None:
                self._act(storm.feed, self._storm_facts(storm))

    def _act(self, feed: str, facts: dict) -> None:
        channel = self.active.get(feed)
        if channel is None:
            self.journal.write("skipped", reason="channel not streaming", **facts)
            return
        if getattr(channel, "clients", 0) <= 0:
            self.journal.write("skipped", reason="no clients", **facts)
            return

        uuid = getattr(channel, "uuid", "")
        name = getattr(channel, "name", "") or uuid
        if self._is_excluded(name):
            self.journal.write("skipped", reason="excluded", channel=name, **facts)
            return

        if self._too_many(uuid):
            self.journal.write("skipped", reason="switch limit reached", channel=name, **facts)
            return

        following = self._following(uuid, feed)
        if following is None:
            self.journal.write("skipped", reason="no source after this one", channel=name, **facts)
            return
        if following.is_slate:
            self.journal.write("skipped", reason="next source is the slate", channel=name, **facts)
            return

        if self.options.observe_only:
            self.switches[uuid].append(time.time())
            self.journal.write("would_switch", channel=name, to=following.name, **facts)
            self._keep_switches()
            return

        try:
            self.client.next_stream(uuid)
        except ApiError as error:
            self.journal.write("failed", channel=name, detail=str(error), **facts)
            return

        self.switches[uuid].append(time.time())
        self.active.pop(feed, None)
        self._status_at = float("-inf")
        self.journal.write("switched", channel=name, to=following.name, **facts)
        self._keep_switches()

    def _following(self, uuid: str, feed: str) -> ChainEntry | None:
        following = self.catalogue.next_entry(uuid, feed)
        now = time.monotonic()
        if following is not None or now - self._catalogue_at < CATALOGUE_RETRY_SECONDS:
            return following
        self._catalogue_at = now
        try:
            self.catalogue = self.client.catalogue()
        except ApiError as error:
            self.journal.write("api_error", where="catalogue", detail=str(error))
            return None
        return self.catalogue.next_entry(uuid, feed)

    def _facts(self, verdict: Verdict) -> dict:
        return {
            "feed": verdict.feed,
            "cause": CAUSE_UNDERFED,
            "percent": verdict.percent,
            "in_mbps": round(verdict.in_mbps, 2),
            "measure": verdict.measure,
            "crate_mbps": round(verdict.crate_mbps, 2),
            "starving_seconds": round(verdict.seconds),
        }

    def _storm_facts(self, storm: Storm) -> dict:
        return {
            "feed": storm.feed,
            "cause": CAUSE_TIMESTAMPS,
            "per_minute": storm.per_minute,
            "storm_seconds": round(storm.seconds),
        }

    def _is_excluded(self, name: str) -> bool:
        return name.strip().casefold() in self.excluded

    def _too_many(self, uuid: str) -> bool:
        recent = self.switches[uuid]
        cutoff = time.time() - HOUR_SECONDS
        while recent and recent[0] < cutoff:
            recent.popleft()
        return len(recent) >= max(self.options.max_switches, 0)

    def _recall_switches(self) -> dict[str, deque[float]]:
        cutoff = time.time() - HOUR_SECONDS
        recalled = {}
        for uuid, moments in load(self.switches_path).items():
            if not isinstance(moments, list):
                continue
            recent = sorted(
                float(moment)
                for moment in moments
                if isinstance(moment, int | float) and moment >= cutoff
            )
            if recent:
                recalled[uuid] = deque(recent)
        return recalled

    def _keep_switches(self) -> None:
        cutoff = time.time() - HOUR_SECONDS
        save(
            self.switches_path,
            {
                uuid: [moment for moment in moments if moment >= cutoff]
                for uuid, moments in self.switches.items()
                if moments and moments[-1] >= cutoff
            },
        )


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
