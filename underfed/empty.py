from __future__ import annotations

import re
from dataclasses import dataclass, field

UPSTREAM = re.compile(
    r"^\S+ \[(?P<feed>\S+)\] (?P<what>upstream EOF|upstream connected|upstream error"
    r"|upstream sent an MP4 file|giving up: no data)"
)


@dataclass(frozen=True)
class EmptySource:
    feed: str


@dataclass
class EmptySourceTracker:
    last_event: dict[str, str] = field(default_factory=dict)

    def observe(self, line: str) -> EmptySource | None:
        found = UPSTREAM.search(line)
        if found is None:
            return None
        feed, what = found.group("feed"), found.group("what")
        if what != "giving up: no data":
            self.last_event[feed] = what
            return None
        ended_empty = self.last_event.pop(feed, None) == "upstream EOF"
        return EmptySource(feed=feed) if ended_empty else None
