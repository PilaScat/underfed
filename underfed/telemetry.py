from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

LINE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4})\s+"
    r"\[(?P<feed>[^\]]+)\]\s+"
    r"cushion=(?P<cushion>\d+)s\((?P<clock>\w+)\)\s+"
    r"buf=(?P<buf>[\d.]+)MB\s+"
    r"out=(?P<out>[\d.]+)Mbps\s+"
    r"in=(?P<inbound>[\d.]+)Mbps\s+"
    r"crate=(?P<crate>[\d.]+)Mbps"
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

    @property
    def ratio(self) -> float:
        if self.crate_mbps <= 0:
            return 1.0
        return self.in_mbps / self.crate_mbps


def parse(line: str) -> Sample | None:
    match = LINE.match(line.strip())
    if match is None:
        return None
    try:
        stamp = datetime.strptime(match["stamp"], "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None
    return Sample(
        at=stamp.timestamp(),
        feed=match["feed"],
        cushion_seconds=int(match["cushion"]),
        clock=match["clock"],
        buffer_mb=float(match["buf"]),
        out_mbps=float(match["out"]),
        in_mbps=float(match["inbound"]),
        crate_mbps=float(match["crate"]),
        reconnects=int(match["reconnects"] or 0),
    )


def parse_all(lines: Iterable[str]) -> list[Sample]:
    samples: list[Sample] = []
    for line in lines:
        sample = parse(str(line))
        if sample is not None:
            samples.append(sample)
    return samples
