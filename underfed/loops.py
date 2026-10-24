from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .detector import Thresholds
from .telemetry import CorruptLoop


@dataclass(frozen=True)
class Loops:
    feed: str
    at: float
    since: float
    count: int

    @property
    def seconds(self) -> float:
        return self.at - self.since


@dataclass
class LoopDetector:
    thresholds: Thresholds = field(default_factory=Thresholds)
    feeds: dict[str, deque[float]] = field(default_factory=dict)

    def observe(self, loop: CorruptLoop) -> Loops | None:
        limit = self.thresholds.loops_count
        if limit <= 0:
            return None
        moments = self.feeds.setdefault(loop.feed, deque())
        moments.append(loop.at)
        window = self.thresholds.loops_minutes * 60
        while moments[0] < loop.at - window:
            moments.popleft()
        if len(moments) < limit:
            return None
        found = Loops(feed=loop.feed, at=loop.at, since=moments[0], count=len(moments))
        moments.clear()
        return found
