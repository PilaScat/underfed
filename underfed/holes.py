from __future__ import annotations

from dataclasses import dataclass, field

from .constants import SAMPLE_GAP_TOLERANCE_SECONDS
from .detector import Thresholds
from .telemetry import Sample

WHAT_VIDEO = "video"
WHAT_AUDIO = "audio"
WHAT_BOTH = "both"


@dataclass(frozen=True)
class Holes:
    feed: str
    at: float
    since: float
    video_percent: int
    audio_percent: int
    what: str

    @property
    def seconds(self) -> float:
        return self.at - self.since

    @property
    def percent(self) -> int:
        return max(self.video_percent, self.audio_percent)

    def describe(self) -> str:
        return f"{self.feed} missing {self.percent}% of its {self.subject} for {self.seconds:.0f}s"

    @property
    def subject(self) -> str:
        return {WHAT_VIDEO: "picture", WHAT_AUDIO: "sound"}.get(self.what, "picture and sound")


@dataclass
class FeedHoles:
    first_seen: float
    last_at: float
    since: float | None = None
    reported_at: float | None = None
    verdicts: int = 0


def missing(sample: Sample) -> tuple[int, int] | None:
    if sample.vholes_percent is None and sample.aholes_percent is None:
        return None
    return sample.vholes_percent or 0, sample.aholes_percent or 0


def what(video: int, audio: int, limit: int) -> str:
    if video >= limit and audio >= limit:
        return WHAT_BOTH
    return WHAT_VIDEO if video >= limit else WHAT_AUDIO


@dataclass
class HolesDetector:
    thresholds: Thresholds = field(default_factory=Thresholds)
    feeds: dict[str, FeedHoles] = field(default_factory=dict)

    def observe(self, sample: Sample) -> Holes | None:
        limit = self.thresholds.holes_percent
        shares = missing(sample)
        if limit <= 0 or shares is None:
            return None
        video, audio = shares
        state = self.feeds.get(sample.feed)
        if state is None or sample.at - state.last_at > SAMPLE_GAP_TOLERANCE_SECONDS:
            state = FeedHoles(first_seen=sample.at, last_at=sample.at)
            self.feeds[sample.feed] = state
        state.last_at = sample.at

        if max(video, audio) < limit:
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
            feed=sample.feed,
            at=sample.at,
            since=state.since,
            video_percent=video,
            audio_percent=audio,
            what=what(video, audio, limit),
        )
