from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = datetime(2026, 9, 8, 20, 0, 0, tzinfo=UTC)
STEP_SECONDS = 15


def stamp(tick: int) -> str:
    moment = BASE + timedelta(seconds=tick * STEP_SECONDS)
    return moment.strftime("%Y-%m-%dT%H:%M:%S%z")


def line(
    tick: int,
    feed: str = "202121.ts",
    cushion: int = 0,
    inbound: float = 1.0,
    crate: float = 4.44,
    out: float = 1.0,
    buf: float = 0.1,
    reconnects: int = 2,
) -> str:
    return (
        f"{stamp(tick)} [{feed}] cushion={cushion}s(pcr) buf={buf}MB "
        f"out={out:.2f}Mbps in={inbound:.2f}Mbps crate={crate:.2f}Mbps "
        f"in_total=1580MB reconnects={reconnects} ccerr=1 pcrrej=0 disc=1 sync=1 pcr_back=0"
    )


def healthy(tick: int, feed: str = "202121.ts") -> str:
    return line(tick, feed=feed, cushion=28, inbound=4.4, out=4.3, buf=14.0)


def starving(tick: int, feed: str = "202121.ts") -> str:
    return line(tick, feed=feed, cushion=0, inbound=1.0, out=0.5)


def ticks(start: int, count: int, builder, **kwargs) -> list[str]:
    return [builder(start + index, **kwargs) for index in range(count)]
