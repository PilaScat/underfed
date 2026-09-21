from __future__ import annotations

import re
from dataclasses import dataclass

FORBIDDEN = re.compile(r"^(?P<stamp>\S+) \[(?P<feed>\S+)\] .*\bHTTP Error 403\b")


@dataclass(frozen=True)
class Refusal:
    feed: str


def parse_refusal(line: str) -> Refusal | None:
    found = FORBIDDEN.search(line)
    return Refusal(feed=found.group("feed")) if found else None
