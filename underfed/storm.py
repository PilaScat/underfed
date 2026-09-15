from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .constants import STORM_WINDOW_SECONDS
from .detector import Thresholds
from .telemetry import Discontinuity


@dataclass(frozen=True)
class Storm:
    feed: str
    at: float
    since: float
    per_minute: int

    @property
    def seconds(self) -> float:
        return self.at - self.since

    def describe(self) -> str:
        return (
            f"{self.feed} at {self.per_minute} timestamp discontinuities a minute "
            f"for {self.seconds:.0f}s"
        )


@dataclass
class FeedStorm:
    moments: deque[float] = field(default_factory=deque)
    since: float | None = None
    reported_at: float | None = None
    verdicts: int = 0


@dataclass
class StormDetector:
    thresholds: Thresholds = field(default_factory=Thresholds)
    feeds: dict[str, FeedStorm] = field(default_factory=dict)

    def observe(self, jump: Discontinuity) -> Storm | None:
        limit = self.thresholds.storm_per_minute
        if limit <= 0:
            return None
        state = self.feeds.setdefault(jump.feed, FeedStorm())
        per_minute = self._count(state.moments, jump.at)
        if per_minute < limit:
            state.since = None
            state.reported_at = None
            return None

        if state.since is None:
            state.since = jump.at
        confirm = self.thresholds.confirm_seconds
        if jump.at - state.since < confirm:
            return None
        if state.reported_at is not None and jump.at - state.reported_at < confirm:
            return None

        state.reported_at = jump.at
        state.verdicts += 1
        return Storm(feed=jump.feed, at=jump.at, since=state.since, per_minute=per_minute)

    @staticmethod
    def _count(moments: deque[float], at: float) -> int:
        moments.append(at)
        while moments[0] <= at - STORM_WINDOW_SECONDS:
            moments.popleft()
        return len(moments)
