from __future__ import annotations

import gzip
import json
import time
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

from conftest import corrupt_loop, healthy, holed, starving, storm, ticks

from underfed.dispatcharr import ActiveChannel, ApiError, Catalogue, ChainEntry
from underfed.watcher import Watcher, arguments

UNO = "202121.ts"


class FakeClient:
    def __init__(self, active: dict, catalogue: Catalogue, fails: bool = False) -> None:
        self._active = active
        self._catalogue = catalogue
        self._fails = fails
        self.breaks = False
        self.switched: list[str] = []
        self.chains: list[tuple[int, list[int]]] = []
        self.catalogue_calls = 0

    def active(self) -> dict:
        if self.breaks:
            raise ValueError("invalid literal for int() with base 10: 'abc'")
        return dict(self._active)

    def catalogue(self) -> Catalogue:
        self.catalogue_calls += 1
        return self._catalogue

    def next_stream(self, uuid: str) -> None:
        if self._fails:
            raise ApiError("boom")
        self.switched.append(uuid)

    def set_chain(self, channel_id: int, stream_ids: list[int]) -> None:
        if self._fails:
            raise ApiError("boom")
        self.chains.append((channel_id, list(stream_ids)))
        for uuid, numeric in self._catalogue.numeric_ids.items():
            if numeric != channel_id:
                continue
            entries = {row.stream_id: row for row in self._catalogue.chains[uuid]}
            self._catalogue.chains[uuid] = [entries[i] for i in stream_ids if i in entries]


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
        "storm_per_minute": 100,
        "storm_confirm_seconds": 15.0,
        "holes_percent": 10,
        "holes_confirm_seconds": 30.0,
        "loops_count": 3,
        "loops_minutes": 5.0,
        "exclude": [],
        "observe_only": False,
        "demote_minutes": 30.0,
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


def storm_on(watcher: Watcher, seconds: int = 50) -> None:
    for text in storm(0, seconds, feed=UNO):
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


def test_a_channel_created_after_the_catalogue_was_read_is_looked_up_again(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), Catalogue())
    client._catalogue = chain_with_alternative()
    starve(watcher)
    assert client.switched == ["uuid-uno"]
    assert client.catalogue_calls == 1


def test_a_channel_still_unknown_is_not_looked_up_more_than_once_a_minute(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), Catalogue())
    starve(watcher, count=12)
    assert client.switched == []
    assert client.catalogue_calls == 1
    assert events(watcher)[-1]["reason"] == "no source after this one"


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


def test_the_hourly_limit_holds_across_a_restart_of_the_watcher(tmp_path: Path):
    first, client = build(tmp_path, streaming(), chain_with_alternative(), max_switches=1)
    starve(first)
    assert client.switched == ["uuid-uno"]

    second, client = build(tmp_path, streaming(), chain_with_alternative(), max_switches=1)
    starve(second)
    assert client.switched == []
    assert events(second)[-1]["reason"] == "switch limit reached"


def test_a_switch_older_than_an_hour_is_forgotten_on_restart(tmp_path: Path):
    stale = time.time() - 3700
    (tmp_path / "switches.json").write_text(
        json.dumps({"uuid-uno": [stale], "uuid-due": "broken"}), encoding="utf-8"
    )
    watcher, client = build(tmp_path, streaming(), chain_with_alternative(), max_switches=1)
    assert dict(watcher.switches) == {}
    starve(watcher)
    assert client.switched == ["uuid-uno"]
    assert list(json.loads((tmp_path / "switches.json").read_text(encoding="utf-8"))) == [
        "uuid-uno"
    ]


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
        watcher._status_at = float("-inf")
        watcher.step()
    errors = [row for row in events(watcher) if row["event"] == "error"]
    assert len(errors) == 1
    assert "ValueError" in errors[0]["detail"]
    client.breaks = False
    watcher._status_at = float("-inf")
    watcher.step()
    starve(watcher)
    assert client.switched == ["uuid-uno"]


def test_a_watcher_started_right_after_boot_reads_status_and_chains_at_once(
    tmp_path: Path, monkeypatch
):
    (tmp_path / "delaybuf.log").write_text("", encoding="utf-8")
    client = FakeClient(streaming(), chain_with_alternative())
    monkeypatch.setattr("underfed.watcher.time.monotonic", lambda: 12.0)
    watcher = Watcher(options(tmp_path), client)  # type: ignore[arg-type]
    watcher.step()
    assert client.catalogue_calls == 1
    assert watcher.active
    starve(watcher)
    assert client.switched == ["uuid-uno"]


def test_the_journal_carries_the_numbers_that_justify_the_move(tmp_path: Path):
    watcher, _ = build(tmp_path, streaming(), chain_with_alternative())
    starve(watcher)
    last = events(watcher)[-1]
    assert last["feed"] == UNO
    assert last["cause"] == "underfed"
    assert last["percent"] == 23
    assert last["in_mbps"] == 1.0
    assert last["crate_mbps"] == 4.44
    assert last["starving_seconds"] >= 45


def test_a_channel_whose_source_storms_is_moved_to_the_next_source(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative())
    storm_on(watcher, seconds=20)
    assert client.switched == ["uuid-uno"]
    last = events(watcher)[-1]
    assert last["event"] == "switched"
    assert last["cause"] == "timestamps"
    assert last["per_minute"] >= 100
    assert last["storm_seconds"] == 15


def test_the_timestamp_rule_at_zero_leaves_the_channel_alone(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative(), storm_per_minute=0)
    storm_on(watcher, seconds=300)
    assert client.switched == []
    assert events(watcher) == []


def test_a_storm_and_a_shortfall_share_the_hourly_limit(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative(), max_switches=1)
    starve(watcher)
    watcher.active = streaming()
    storm_on(watcher)
    assert client.switched == ["uuid-uno"]
    last = events(watcher)[-1]
    assert last["reason"] == "switch limit reached"
    assert last["cause"] == "timestamps"


def test_the_arguments_of_an_apply_made_before_the_rule_existed_turn_it_on():
    assert arguments(["--journal", "x"]).storm_per_minute == 100


def test_a_channel_whose_source_keeps_looping_is_moved_to_the_next_source(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative())
    for second in (0, 105, 160):
        watcher._consume(corrupt_loop(second, feed=UNO))
    assert client.switched == ["uuid-uno"]
    last = events(watcher)[-1]
    assert last["event"] == "switched"
    assert last["cause"] == "loops"
    assert last["loops"] == 3
    assert last["loops_seconds"] == 160


def test_the_loop_rule_at_zero_leaves_the_channel_alone(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative(), loops_count=0)
    for second in range(0, 300, 10):
        watcher._consume(corrupt_loop(second, feed=UNO))
    assert client.switched == []
    assert events(watcher) == []


def test_an_apply_made_before_the_loop_rule_existed_gets_it_with_three_in_five_minutes():
    applied = arguments(["--journal", "x"])
    assert (applied.loops_count, applied.loops_minutes) == (3, 5)


REFUSED = (
    "2026-09-20T19:42:11+0000 [202121.ts] upstream error HTTPError: "
    "HTTP Error 403: Forbidden; retry in 1s"
)


def test_a_refused_source_goes_to_the_back_of_the_chain(tmp_path: Path):
    cat = chain_with_alternative()
    before = [row.stream_id for row in cat.chains["uuid-uno"]]
    watcher, client = build(tmp_path, streaming(), cat)
    watcher._consume(REFUSED)

    assert len(client.chains) == 1
    channel_id, order = client.chains[0]
    assert channel_id == 189
    assert order == [before[1], before[0], before[2]]
    demoted = [row for row in events(watcher) if row["event"] == "demoted"]
    assert demoted and demoted[0]["cause"] == "forbidden"
    assert demoted[0]["feed"] == UNO


def test_the_slate_stays_last(tmp_path: Path):
    cat = chain_with_alternative()
    slate = cat.chains["uuid-uno"][2].stream_id
    watcher, client = build(tmp_path, streaming(), cat)
    watcher._consume(REFUSED)
    assert client.chains[0][1][-1] == slate


def test_one_refusal_is_enough_but_the_second_changes_nothing(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative())
    watcher._consume(REFUSED)
    watcher._consume(REFUSED)
    assert len(client.chains) == 1


def test_a_source_with_nowhere_lower_is_left_alone(tmp_path: Path):
    cat = catalogue(
        [entry(UNO, "Sky Sport Uno FHD"), entry("slate.ts", "Could Not Dispatch", slate=True)]
    )
    watcher, client = build(tmp_path, streaming(), cat)
    watcher._consume(REFUSED)
    assert client.chains == []
    skipped = [row for row in events(watcher) if row["event"] == "skipped"]
    assert skipped and skipped[-1]["reason"] == "nowhere lower to go"


def test_the_source_climbs_back_when_the_half_hour_is_over(tmp_path: Path):
    cat = chain_with_alternative()
    before = [row.stream_id for row in cat.chains["uuid-uno"]]
    watcher, client = build(tmp_path, streaming(), cat)
    watcher._consume(REFUSED)
    watcher.demotions[0] = replace(watcher.demotions[0], until=time.time() - 1)
    watcher._restore_due()

    assert len(client.chains) == 2
    assert client.chains[1][1] == before
    assert [row["event"] for row in events(watcher)].count("restored") == 1


def test_it_waits_while_the_half_hour_runs(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative())
    watcher._consume(REFUSED)
    watcher._restore_due()
    assert len(client.chains) == 1


def test_the_demotions_survive_a_restart(tmp_path: Path):
    cat = chain_with_alternative()
    before = [row.stream_id for row in cat.chains["uuid-uno"]]
    watcher, _ = build(tmp_path, streaming(), cat)
    watcher._consume(REFUSED)

    again, client = build(tmp_path, streaming(), cat)
    assert [row.feed for row in again.demotions] == [UNO]
    again.demotions[0] = replace(again.demotions[0], until=time.time() - 1)
    again._restore_due()
    assert client.chains == [(189, before)]


def test_observe_only_writes_it_down_and_touches_nothing(tmp_path: Path):
    watcher, client = build(
        tmp_path, streaming(), chain_with_alternative(), observe_only=True
    )
    watcher._consume(REFUSED)
    assert client.chains == []
    assert [row["event"] for row in events(watcher)].count("would_demote") == 1


def test_zero_minutes_turns_the_whole_thing_off(tmp_path: Path):
    watcher, client = build(
        tmp_path, streaming(), chain_with_alternative(), demote_minutes=0
    )
    watcher._consume(REFUSED)
    assert client.chains == []


def upstream(feed: str, *lines: str) -> list[str]:
    return [f"2026-10-10T18:45:07+0000 [{feed}] {line}" for line in lines]


GIVE_UP = (
    "giving up: no data after 1 upstream attempts (RESV_GIVEUP_TRIES=1); "
    "exiting so Dispatcharr can try the next stream"
)


def test_a_source_that_closes_without_data_goes_to_the_back_of_the_chain(tmp_path: Path):
    cat = chain_with_alternative()
    before = [row.stream_id for row in cat.chains["uuid-uno"]]
    watcher, client = build(tmp_path, streaming(), cat)
    for text in upstream(UNO, "upstream connected edge=piwirejumupa.lol", "upstream EOF", GIVE_UP):
        watcher._consume(text)

    assert client.chains == [(189, [before[1], before[0], before[2]])]
    demoted = [row for row in events(watcher) if row["event"] == "demoted"]
    assert demoted and demoted[0]["cause"] == "empty"


def test_an_mp4_or_a_refused_connection_is_not_an_empty_source(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative())
    mp4 = upstream(
        UNO,
        "upstream connected edge=89.45.12.143:80",
        "upstream sent an MP4 file, not a live TS; counted as an attempt without data",
        GIVE_UP,
    )
    full = upstream(
        UNO,
        "upstream error HTTPError: HTTP Error 407: Proxy Authentication Required; retry in 1s",
        GIVE_UP,
    )
    for text in mp4 + full:
        watcher._consume(text)
    assert client.chains == []


def test_an_eof_after_data_is_not_an_empty_source(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative())
    for text in upstream(UNO, "upstream EOF", "upstream connected edge=piwirejumupa.lol"):
        watcher._consume(text)
    assert client.chains == []


WEB_3 = Path(__file__).parent / "fixtures" / "delaybuf-2026-10-10.log.gz"


def test_the_evening_of_10_october_demotes_the_hanging_source_once(tmp_path: Path):
    chain = [
        entry("542034.ts", "DAZN WEB 3 FULL HD"),
        entry("542033.ts", "DAZN WEB 3 HD"),
        entry("542032.ts", "DAZN WEB 3 SD"),
        entry("slate.ts", "Could Not Dispatch", slate=True),
    ]
    ids = [row.stream_id for row in chain]
    hanging = ActiveChannel(uuid="uuid-uno", name="DAZN | Web 3", feed="542034.ts", clients=1)
    active = {"542034.ts": hanging}
    watcher, client = build(tmp_path, active, catalogue(chain))
    for text in gzip.decompress(WEB_3.read_bytes()).decode("utf-8").splitlines():
        watcher._consume(text)

    assert client.chains == [(189, [ids[1], ids[2], ids[0], ids[3]])]
    demoted = [row for row in events(watcher) if row["event"] == "demoted"]
    assert [(row["feed"], row["cause"]) for row in demoted] == [("542034.ts", "empty")]


def test_a_channel_missing_half_its_video_is_moved_to_the_next_source(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative())

    for text in ticks(0, 6, holed, feed=UNO):
        watcher._consume(text)

    assert client.switched == ["uuid-uno"]
    switched = [row for row in events(watcher) if row["event"] == "switched"]
    assert switched[0]["cause"] == "holes"
    assert switched[0]["vholes_percent"] == 50
    assert switched[0]["aholes_percent"] == 50
    assert switched[0]["what"] == "both"


def test_missing_video_counts_against_the_hourly_limit(tmp_path: Path):
    watcher, client = build(tmp_path, streaming(), chain_with_alternative(), max_switches=1)
    starve(watcher)
    watcher.active = client.active()

    for text in ticks(20, 6, holed, feed=UNO):
        watcher._consume(text)

    assert client.switched == ["uuid-uno"]
    assert events(watcher)[-1]["reason"] == "switch limit reached"
