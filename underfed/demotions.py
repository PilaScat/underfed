from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .dispatcharr import ChainEntry


@dataclass(frozen=True)
class Demotion:
    uuid: str
    stream_id: int
    feed: str
    position: int
    until: float


def demoted_order(chain: Sequence[ChainEntry], stream_id: int) -> list[int] | None:
    ids = [entry.stream_id for entry in chain]
    if stream_id not in ids:
        return None
    sources = [entry for entry in chain if not entry.is_slate]
    if len(sources) < 2:
        return None
    if sources[-1].stream_id == stream_id:
        return None
    moved = [entry.stream_id for entry in sources if entry.stream_id != stream_id]
    moved.append(stream_id)
    moved.extend(entry.stream_id for entry in chain if entry.is_slate)
    return moved


def position_of(chain: Sequence[ChainEntry], stream_id: int) -> int | None:
    for index, entry in enumerate(chain):
        if entry.stream_id == stream_id:
            return index
    return None


def restored_order(
    chain: Sequence[ChainEntry], stream_id: int, position: int
) -> list[int] | None:
    ids = [entry.stream_id for entry in chain]
    if stream_id not in ids or position >= len(ids):
        return None
    if ids.index(stream_id) == position:
        return None
    rest = [identifier for identifier in ids if identifier != stream_id]
    rest.insert(position, stream_id)
    return rest
