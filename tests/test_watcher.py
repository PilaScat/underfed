from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from conftest import healthy, starving, ticks

from underfed.dispatcharr import ActiveChannel, ApiError, Catalogue, ChainEntry
from underfed.watcher import Watcher

UNO = "202121.ts"


class FakeClient:
    def __init__(self, active: dict, catalogue: Catalogue, fails: bool = False) -> None:
        self._active = active
        self._catalogue = catalogue
        self._fails = fails
        self.breaks = False
        self.switched: list[str] = []

    def active(self) -> dict:
        if self.breaks:
            raise ValueError("invalid literal for int() with base 10: 'abc'")
        return dict(self._active)

    def catalogue(self) -> Catalogue:
        return self._catalogue

    def next_stream(self, uuid: str) -> None:
        if self._fails:
            raise ApiError("boom")
        self.switched.append(uuid)


def entry(feed: str, name: str, slate: bool = False) -> ChainEntry:
    return ChainEntry(stream_id=abs(hash(feed)) % 10000, feed=feed, name=name, is_slate=slate)


def catalogue(chain: list[ChainEntry]) -> Catalogue:
    return Catalogue(chains={"uuid-uno": chain}, numeric_ids={"uuid-uno": 189})


def chain_with_alternative() -> Catalogue:
    return catalogue(
        [
            entry(UNO, "Sky Sport Uno FHD"),
            entry("548109.ts", "Sky Sport Uno FHD"),
            entry("slate.ts", "Could Not Dispatch", slate=True),
        ]
    )


def options(tmp_path: Path, **overrides) -> Namespace:
    values = {
        "telemetry": str(tmp_path / "delaybuf.log"),
        "api_url": "http://127.0.0.1:9191",
        "journal": str(tmp_path / "journal.jsonl"),
        "ratio_percent": 70.0,
        "confirm_seconds": 45.0,
        "warmup_seconds": 60.0,
        "stable_seconds": 180.0,
        "max_switches": 2,
        "exclude": [],
        "observe_only": False,
    }
    values.update(overrides)
    return Namespace(**values)


def build(tmp_path: Path, active: dict, cat: Catalogue, **overrides) -> tuple[Watcher, FakeClient]:
    (tmp_path / "delaybuf.log").write_text("", encoding="utf-8")
    client = FakeClient(active, cat, fails=overrides.pop("fails", False))
    watcher = Watcher(options(tmp_path, **overrides), client)  # type: ignore[arg-type]
    watcher.active = client.active()
    watcher.catalogue = cat
    return watcher, client


def starve(watcher: Watcher, count: int = 4) -> None:
    for text in ticks(0, 5, healthy) + ticks(5, count, starving):
        watcher._consume(text)


def streaming(clients: int = 2) -> dict:
    return {UNO: ActiveChannel(uuid="uuid-uno", name="Sky | Sport Uno", feed=UNO, clients=clients)}


def events(watcher: Watcher) -> list[dict]:
    return watcher.journal.read()


def test_a_starving_channel_with_viewers_is_moved_to_the_next_source(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative())
    starve(watcher)
    assert client.switched == ["uuid-uno"]
    assert [row["event"] for row in events(watcher)][-1] == "switched"


def test_observe_only_records_the_move_without_making_it(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative(), observe_only=True)
    starve(watcher)
    assert client.switched == []
    last = events(watcher)[-1]
    assert last["event"] == "would_switch"
    assert last["to"] == "Sky Sport Uno FHD"


def test_a_channel_nobody_is_watching_is_left_alone(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(clients=0), chain_with_alternative())
    starve(watcher)
    assert client.switched == []
    assert events(watcher)[-1]["reason"] == "no clients"


def test_a_channel_that_is_not_streaming_is_left_alone(tmp_path: Path):
    watcher, client = build(tmp_path, {}, chain_with_alternative())
    starve(watcher)
    assert client.switched == []
    assert events(watcher)[-1]["reason"] == "channel not streaming"


def test_it_never_moves_a_channel_onto_the_slate(tmp_path: Path):
    only_slate = catalogue(
        [entry(UNO, "Sky Sport Uno FHD"), entry("slate.ts", "Slate", slate=True)]
    )
    watcher, client = build(tmp_path, streaming(), only_slate)
    starve(watcher)
    assert client.switched == []
    assert events(watcher)[-1]["reason"] == "next source is the slate"


def test_a_source_with_nothing_after_it_is_left_alone(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), catalogue([entry(UNO, "Sky Sport Uno FHD")]))
    starve(watcher)
    assert client.switched == []
    assert events(watcher)[-1]["reason"] == "no source after this one"


def test_an_excluded_channel_is_left_alone(tmp_path: Path):
    watcher, client = build(
        tmp_path, streaming(), chain_with_alternative(), exclude=["sky | sport uno"]
    )
    starve(watcher)
    assert client.switched == []
    assert events(watcher)[-1]["reason"] == "excluded"


def test_the_hourly_limit_stops_a_channel_bouncing(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative(), max_switches=1)
    for round_number in range(3):
        watcher.active = streaming()
        for text in ticks(round_number * 200, 5, healthy) + ticks(
            round_number * 200 + 5, 4, starving
        ):
            watcher._consume(text)
    assert len(client.switched) == 1
    assert any(row.get("reason") == "switch limit reached" for row in events(watcher))


def test_observe_only_counts_against_the_hourly_limit_as_live_mode_would(tmp_path: Path):
    watcher, client = build(
        tmp_path, streaming(), chain_with_alternative(), max_switches=1, observe_only=True
    )
    for round_number in range(3):
        watcher.active = streaming()
        for text in ticks(round_number * 200, 5, healthy) + ticks(
            round_number * 200 + 5, 4, starving
        ):
            watcher._consume(text)
    kinds = [row.get("reason") or row["event"] for row in events(watcher)]
    assert kinds.count("would_switch") == 1
    assert "switch limit reached" in kinds
    assert client.switched == []


def test_a_failed_call_is_recorded_and_not_counted_as_a_switch(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative(), fails=True)
    starve(watcher)
    assert client.switched == []
    assert events(watcher)[-1]["event"] == "failed"
    assert len(watcher.switches["uuid-uno"]) == 0


def test_an_unexpected_error_is_recorded_once_and_the_watcher_goes_on(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative())
    client.breaks = True
    for _ in range(3):
        watcher._status_at = 0.0
        watcher.step()
    errors = [row for row in events(watcher) if row["event"] == "error"]
    assert len(errors) == 1
    assert "ValueError" in errors[0]["detail"]
    client.breaks = False
    watcher._status_at = 0.0
    watcher.step()
    starve(watcher)
    assert client.switched == ["uuid-uno"]


def test_the_journal_carries_the_numbers_that_justify_the_move(tmp_path: Path):
    watcher, _ = build(tmp_path, streaming(), chain_with_alternative())
    starve(watcher)
    last = events(watcher)[-1]
    assert last["feed"] == UNO
    assert last["percent"] == 23
    assert last["in_mbps"] == 1.0
    assert last["crate_mbps"] == 4.44
    assert last["starving_seconds"] >= 45
