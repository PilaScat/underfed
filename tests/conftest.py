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
    total: int | None = None,
) -> str:
    counter = f"in_total={total}MB " if total is not None else ""
    return (
        f"{stamp(tick)} [{feed}] cushion={cushion}s(pcr) buf={buf}MB "
        f"out={out:.2f}Mbps in={inbound:.2f}Mbps crate={crate:.2f}Mbps "
        f"{counter}reconnects={reconnects} ccerr=1 pcrrej=0 disc=1 sync=1 pcr_back=0"
    )


def healthy(tick: int, feed: str = "202121.ts") -> str:
    return line(tick, feed=feed, cushion=28, inbound=4.4, out=4.3, buf=14.0)


def starving(tick: int, feed: str = "202121.ts") -> str:
    return line(tick, feed=feed, cushion=0, inbound=1.0, out=0.5)


def ticks(start: int, count: int, builder, **kwargs) -> list[str]:
    return [builder(start + index, **kwargs) for index in range(count)]


def discontinuity(second: int, feed: str = "542059.ts", video: bool = True) -> str:
    moment = (BASE + timedelta(seconds=second)).strftime("%Y-%m-%dT%H:%M:%S%z")
    stream, stream_id = ("vist#0:0/h264", 256) if video else ("aist#0:1/aac", 257)
    return (
        f"{moment} [{feed}] ffmpeg: [{stream} @ 0x55c7ee1ac2c0] "
        f"timestamp discontinuity (stream id={stream_id}): 331826689, new offset= 0"
    )


def storm(start: int, seconds: int, per_second: int = 28, feed: str = "542059.ts") -> list[str]:
    return [
        discontinuity(second, feed=feed, video=index % 2 == 0)
        for second in range(start, start + seconds)
        for index in range(per_second)
    ]
