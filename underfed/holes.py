from __future__ import annotations

from dataclasses import dataclass, field

from .constants import SAMPLE_GAP_TOLERANCE_SECONDS
from .detector import Thresholds
from .telemetry import Sample


@dataclass(frozen=True)
class Holes:
    feed: str
    at: float
    since: float
    percent: int

    @property
    def seconds(self) -> float:
        return self.at - self.since

    def describe(self) -> str:
        return f"{self.feed} missing {self.percent}% of its video for {self.seconds:.0f}s"


@dataclass
class FeedHoles:
    first_seen: float
    last_at: float
    since: float | None = None
    reported_at: float | None = None
    verdicts: int = 0


@dataclass
class HolesDetector:
    thresholds: Thresholds = field(default_factory=Thresholds)
    feeds: dict[str, FeedHoles] = field(default_factory=dict)

    def observe(self, sample: Sample) -> Holes | None:
        limit = self.thresholds.holes_percent
        if limit <= 0 or sample.holes_percent is None:
            return None
        state = self.feeds.get(sample.feed)
        if state is None or sample.at - state.last_at > SAMPLE_GAP_TOLERANCE_SECONDS:
            state = FeedHoles(first_seen=sample.at, last_at=sample.at)
            self.feeds[sample.feed] = state
        state.last_at = sample.at

        if sample.holes_percent < limit:
            state.since = None
            state.reported_at = None
            return None

        if state.since is None:
            state.since = sample.at
        if sample.at - state.first_seen < self.thresholds.warmup_seconds:
            return None
        confirm = self.thresholds.holes_confirm_seconds
        if sample.at - state.since < confirm:
            return None
        if state.reported_at is not None and sample.at - state.reported_at < confirm:
            return None

        state.reported_at = sample.at
        state.verdicts += 1
        return Holes(
            feed=sample.feed, at=sample.at, since=state.since, percent=sample.holes_percent
        )
