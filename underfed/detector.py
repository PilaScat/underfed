from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .constants import (
    DEFAULT_CONFIRM_SECONDS,
    DEFAULT_RATIO_PERCENT,
    DEFAULT_STABLE_SECONDS,
    DEFAULT_STORM_PER_MINUTE,
    DEFAULT_WARMUP_SECONDS,
    INGEST_MIN_SPAN_SECONDS,
    INGEST_WINDOW_SECONDS,
    MIN_TRUSTED_CRATE_MBPS,
    SAMPLE_GAP_TOLERANCE_SECONDS,
)
from .telemetry import Sample

MEASURE_TOTAL = "in_total"
MEASURE_AVERAGE = "in"


@dataclass(frozen=True)
class Thresholds:
    ratio: float = DEFAULT_RATIO_PERCENT / 100
    confirm_seconds: float = DEFAULT_CONFIRM_SECONDS
    warmup_seconds: float = DEFAULT_WARMUP_SECONDS
    stable_seconds: float = DEFAULT_STABLE_SECONDS
    min_crate_mbps: float = MIN_TRUSTED_CRATE_MBPS
    storm_per_minute: int = DEFAULT_STORM_PER_MINUTE

    @classmethod
    def from_settings(cls, settings: dict) -> Thresholds:
        def number(key: str, fallback: float) -> float:
            try:
                return float(str(settings.get(key, fallback)))
            except (TypeError, ValueError):
                return fallback

        percent = number("ratio_percent", DEFAULT_RATIO_PERCENT)
        return cls(
            ratio=min(max(percent, 1.0), 99.0) / 100,
            confirm_seconds=max(number("confirm_seconds", DEFAULT_CONFIRM_SECONDS), 5.0),
            warmup_seconds=max(number("warmup_seconds", DEFAULT_WARMUP_SECONDS), 0.0),
            stable_seconds=max(number("stable_seconds", DEFAULT_STABLE_SECONDS), 0.0),
            storm_per_minute=max(int(number("storm_per_minute", DEFAULT_STORM_PER_MINUTE)), 0),
        )


@dataclass(frozen=True)
class Verdict:
    feed: str
    at: float
    starving_since: float
    in_mbps: float
    crate_mbps: float
    measure: str = MEASURE_AVERAGE

    @property
    def seconds(self) -> float:
        return self.at - self.starving_since

    @property
    def percent(self) -> int:
        if self.crate_mbps <= 0:
            return 100
        return round(100 * self.in_mbps / self.crate_mbps)

    def describe(self) -> str:
        return (
            f"{self.feed} at {self.percent}% of content rate "
            f"({self.in_mbps:.2f} of {self.crate_mbps:.2f} Mbps) for {self.seconds:.0f}s"
        )


@dataclass
class FeedState:
    first_seen: float
    last_at: float
    last_sample: Sample
    starving_since: float | None = None
    healthy_since: float | None = None
    reported_at: float | None = None
    verdicts: int = 0
    totals: deque[tuple[float, int]] = field(default_factory=deque)
    ingest_mbps: float = 0.0
    measure: str = MEASURE_AVERAGE


def ingest(state: FeedState, sample: Sample) -> tuple[float, str]:
    totals = state.totals
    if sample.total_mb is None:
        totals.clear()
        return sample.in_mbps, MEASURE_AVERAGE
    if totals and sample.total_mb < totals[-1][1]:
        totals.clear()
    totals.append((sample.at, sample.total_mb))
    while len(totals) >= 2 and totals[1][0] <= sample.at - INGEST_WINDOW_SECONDS:
        totals.popleft()
    first_at, first_total = totals[0]
    span = sample.at - first_at
    if span < INGEST_MIN_SPAN_SECONDS:
        return sample.in_mbps, MEASURE_AVERAGE
    return (sample.total_mb - first_total) * 8 / span, MEASURE_TOTAL


@dataclass
class Detector:
    thresholds: Thresholds = field(default_factory=Thresholds)
    feeds: dict[str, FeedState] = field(default_factory=dict)

    def observe(self, sample: Sample) -> Verdict | None:
        state = self.feeds.get(sample.feed)
        if state is None or sample.at - state.last_at > SAMPLE_GAP_TOLERANCE_SECONDS:
            state = FeedState(first_seen=sample.at, last_at=sample.at, last_sample=sample)
            state.ingest_mbps, state.measure = ingest(state, sample)
            self.feeds[sample.feed] = state
            return None

        state.last_at = sample.at
        state.last_sample = sample
        state.ingest_mbps, state.measure = ingest(state, sample)

        if sample.crate_mbps < self.thresholds.min_crate_mbps:
            return None

        if not self._is_starving(state, sample):
            self._recover(state, sample.at)
            return None

        state.healthy_since = None
        if state.starving_since is None:
            state.starving_since = sample.at
        if sample.at - state.first_seen < self.thresholds.warmup_seconds:
            return None
        if sample.at - state.starving_since < self.thresholds.confirm_seconds:
            return None
        if (
            state.reported_at is not None
            and sample.at - state.reported_at < self.thresholds.confirm_seconds
        ):
            return None

        state.reported_at = sample.at
        state.verdicts += 1
        return Verdict(
            feed=sample.feed,
            at=sample.at,
            starving_since=state.starving_since,
            in_mbps=state.ingest_mbps,
            crate_mbps=sample.crate_mbps,
            measure=state.measure,
        )

    def _is_starving(self, state: FeedState, sample: Sample) -> bool:
        if sample.crate_mbps <= 0:
            return False
        ratio = state.ingest_mbps / sample.crate_mbps
        return ratio < self.thresholds.ratio and sample.cushion_seconds == 0

    def _recover(self, state: FeedState, at: float) -> None:
        if state.healthy_since is None:
            state.healthy_since = at
        if at - state.healthy_since >= self.thresholds.stable_seconds:
            state.starving_since = None
            state.reported_at = None

    def snapshot(self, now: float) -> list[dict]:
        rows = []
        for feed, state in sorted(self.feeds.items()):
            sample = state.last_sample
            crate = sample.crate_mbps
            rows.append(
                {
                    "feed": feed,
                    "age": round(now - state.last_at, 1),
                    "percent": round(100 * state.ingest_mbps / crate) if crate > 0 else 100,
                    "in_mbps": round(state.ingest_mbps, 2),
                    "measure": state.measure,
                    "crate_mbps": crate,
                    "cushion": sample.cushion_seconds,
                    "starving_for": (
                        None
                        if state.starving_since is None
                        else round(state.last_at - state.starving_since, 1)
                    ),
                    "verdicts": state.verdicts,
                }
            )
        return rows
