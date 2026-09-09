from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .detector import Detector, Thresholds
from .telemetry import parse


@dataclass(frozen=True)
class Hit:
    feed: str
    at: float
    percent: int
    in_mbps: float
    crate_mbps: float
    seconds: float

    def when(self, offset_hours: float) -> str:
        moment = datetime.fromtimestamp(self.at, tz=UTC)
        shifted = moment.timestamp() + offset_hours * 3600
        return datetime.fromtimestamp(shifted, tz=UTC).strftime("%d %b %H:%M:%S")


@dataclass(frozen=True)
class Replay:
    lines: int
    samples: int
    feeds: dict[str, int]
    hits: list[Hit]

    def summary(self, offset_hours: float = 0.0) -> str:
        if not self.samples:
            return f"No telemetry found in {self.lines} line(s). Is the path right?"
        if not self.hits:
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
        return " ".join(parts)


def run(path: Path, thresholds: Thresholds) -> Replay:
    detector = Detector(thresholds)
    hits: list[Hit] = []
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
    return Replay(lines=lines, samples=samples, feeds=feeds, hits=hits)
