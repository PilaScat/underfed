from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .detector import Detector, Thresholds
from .storm import StormDetector
from .telemetry import parse, parse_discontinuity


def when(at: float, offset_hours: float) -> str:
    shifted = at + offset_hours * 3600
    return datetime.fromtimestamp(shifted, tz=UTC).strftime("%d %b %H:%M:%S")


@dataclass(frozen=True)
class Hit:
    feed: str
    at: float
    percent: int
    in_mbps: float
    crate_mbps: float
    seconds: float

    def when(self, offset_hours: float) -> str:
        return when(self.at, offset_hours)


@dataclass(frozen=True)
class StormHit:
    feed: str
    at: float
    per_minute: int
    seconds: float

    def when(self, offset_hours: float) -> str:
        return when(self.at, offset_hours)


@dataclass(frozen=True)
class Replay:
    lines: int
    samples: int
    feeds: dict[str, int]
    hits: list[Hit]
    storms: list[StormHit]

    def summary(self, offset_hours: float = 0.0) -> str:
        if not self.samples:
            return f"No telemetry found in {self.lines} line(s). Is the path right?"
        if not self.hits and not self.storms:
            return (
                f"{self.samples} sample(s) across {len(self.feeds)} source(s): "
                f"nothing would have been switched."
            )
        per_feed: dict[str, list[Hit]] = {}
        for hit in self.hits:
            per_feed.setdefault(hit.feed, []).append(hit)
        parts = [
            f"{self.samples} sample(s) across {len(self.feeds)} source(s); "
            f"{len(self.hits)} trigger(s) on {len(per_feed)} source(s)."
        ]
        for feed, hits in sorted(per_feed.items(), key=lambda item: -len(item[1])):
            first = hits[0]
            parts.append(
                f"{feed}: {len(hits)} trigger(s), first at {first.when(offset_hours)} "
                f"at {first.percent}% of content rate."
            )
        per_storm: dict[str, list[StormHit]] = {}
        for storm in self.storms:
            per_storm.setdefault(storm.feed, []).append(storm)
        if per_storm:
            parts.append(
                f"{len(self.storms)} trigger(s) on timestamp discontinuities, "
                f"on {len(per_storm)} source(s)."
            )
        for feed, storms in sorted(per_storm.items(), key=lambda item: -len(item[1])):
            opening = storms[0]
            parts.append(
                f"{feed}: {len(storms)} trigger(s), first at {opening.when(offset_hours)} "
                f"at {opening.per_minute} a minute."
            )
        return " ".join(parts)


def run(path: Path, thresholds: Thresholds) -> Replay:
    detector = Detector(thresholds)
    storm_detector = StormDetector(thresholds)
    hits: list[Hit] = []
    storms: list[StormHit] = []
    feeds: dict[str, int] = {}
    lines = 0
    samples = 0
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError as error:
        raise FileNotFoundError(f"Cannot read {path}: {error}") from error
    with handle:
        for line in handle:
            lines += 1
            sample = parse(line)
            if sample is None:
                jump = parse_discontinuity(line)
                storm = storm_detector.observe(jump) if jump is not None else None
                if storm is not None:
                    storms.append(
                        StormHit(
                            feed=storm.feed,
                            at=storm.at,
                            per_minute=storm.per_minute,
                            seconds=storm.seconds,
                        )
                    )
                continue
            samples += 1
            feeds[sample.feed] = feeds.get(sample.feed, 0) + 1
            verdict = detector.observe(sample)
            if verdict is not None:
                hits.append(
                    Hit(
                        feed=verdict.feed,
                        at=verdict.at,
                        percent=verdict.percent,
                        in_mbps=verdict.in_mbps,
                        crate_mbps=verdict.crate_mbps,
                        seconds=verdict.seconds,
                    )
                )
    return Replay(lines=lines, samples=samples, feeds=feeds, hits=hits, storms=storms)
