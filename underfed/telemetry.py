from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

STAMP_AND_FEED = (
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4})\s+"
    r"\[(?P<feed>[^\]]+)\]\s+"
)
DISCONTINUITY = re.compile(STAMP_AND_FEED + r"ffmpeg:.*\btimestamp discontinuity\b")
LINE = re.compile(
    STAMP_AND_FEED
    + r"cushion=(?P<cushion>\d+)s\((?P<clock>\w+)\)\s+"
    r"buf=(?P<buf>[\d.]+)MB\s+"
    r"out=(?P<out>[\d.]+)Mbps\s+"
    r"in=(?P<inbound>[\d.]+)Mbps\s+"
    r"crate=(?P<crate>[\d.]+)Mbps"
    r"(?:\s+in_total=(?P<total>\d+)MB)?"
    r"(?:.*?\breconnects=(?P<reconnects>\d+))?"
)


@dataclass(frozen=True)
class Sample:
    at: float
    feed: str
    cushion_seconds: int
    clock: str
    buffer_mb: float
    out_mbps: float
    in_mbps: float
    crate_mbps: float
    reconnects: int
    total_mb: int | None = None

    @property
    def ratio(self) -> float:
        if self.crate_mbps <= 0:
            return 1.0
        return self.in_mbps / self.crate_mbps


@dataclass(frozen=True)
class Discontinuity:
    at: float
    feed: str


def moment(stamp: str) -> float | None:
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except ValueError:
        return None


def parse(line: str) -> Sample | None:
    match = LINE.match(line.strip())
    if match is None:
        return None
    at = moment(match["stamp"])
    if at is None:
        return None
    return Sample(
        at=at,
        feed=match["feed"],
        cushion_seconds=int(match["cushion"]),
        clock=match["clock"],
        buffer_mb=float(match["buf"]),
        out_mbps=float(match["out"]),
        in_mbps=float(match["inbound"]),
        crate_mbps=float(match["crate"]),
        reconnects=int(match["reconnects"] or 0),
        total_mb=int(match["total"]) if match["total"] is not None else None,
    )


def parse_discontinuity(line: str) -> Discontinuity | None:
    match = DISCONTINUITY.match(line.strip())
    if match is None:
        return None
    at = moment(match["stamp"])
    if at is None:
        return None
    return Discontinuity(at=at, feed=match["feed"])


def parse_all(lines: Iterable[str]) -> list[Sample]:
    samples: list[Sample] = []
    for line in lines:
        sample = parse(str(line))
        if sample is not None:
            samples.append(sample)
    return samples
