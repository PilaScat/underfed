from __future__ import annotations

from dataclasses import dataclass, field

from .constants import (
    DEFAULT_CONFIRM_SECONDS,
    DEFAULT_RATIO_PERCENT,
    DEFAULT_STABLE_SECONDS,
    DEFAULT_WARMUP_SECONDS,
    MIN_TRUSTED_CRATE_MBPS,
    SAMPLE_GAP_TOLERANCE_SECONDS,
)
from .telemetry import Sample


@dataclass(frozen=True)
class Thresholds:
    ratio: float = DEFAULT_RATIO_PERCENT / 100
    confirm_seconds: float = DEFAULT_CONFIRM_SECONDS
    warmup_seconds: float = DEFAULT_WARMUP_SECONDS
    stable_seconds: float = DEFAULT_STABLE_SECONDS
    min_crate_mbps: float = MIN_TRUSTED_CRATE_MBPS

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
        )


@dataclass(frozen=True)
class Verdict:
    feed: str
    at: float
    starving_since: float
    in_mbps: float
    crate_mbps: float

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


@dataclass
class Detector:
    thresholds: Thresholds = field(default_factory=Thresholds)
    feeds: dict[str, FeedState] = field(default_factory=dict)

    def observe(self, sample: Sample) -> Verdict | None:
        state = self.feeds.get(sample.feed)
        if state is None or sample.at - state.last_at > SAMPLE_GAP_TOLERANCE_SECONDS:
            self.feeds[sample.feed] = FeedState(
                first_seen=sample.at, last_at=sample.at, last_sample=sample
            )
            return None

        state.last_at = sample.at
        state.last_sample = sample

        if sample.crate_mbps < self.thresholds.min_crate_mbps:
            self._recover(state, sample.at)
            return None

        if not self._is_starving(sample):
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
            in_mbps=sample.in_mbps,
            crate_mbps=sample.crate_mbps,
        )

    def _is_starving(self, sample: Sample) -> bool:
        return sample.ratio < self.thresholds.ratio and sample.cushion_seconds == 0

    def _recover(self, state: FeedState, at: float) -> None:
        state.starving_since = None
        state.reported_at = None
        if state.healthy_since is None:
            state.healthy_since = at

    def settled_since(self, feed: str) -> float | None:
        state = self.feeds.get(feed)
        return None if state is None else state.healthy_since

    def snapshot(self, now: float) -> list[dict]:
        rows = []
        for feed, state in sorted(self.feeds.items()):
            sample = state.last_sample
            rows.append(
                {
                    "feed": feed,
                    "age": round(now - state.last_at, 1),
                    "percent": round(100 * sample.ratio),
                    "in_mbps": sample.in_mbps,
                    "crate_mbps": sample.crate_mbps,
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
