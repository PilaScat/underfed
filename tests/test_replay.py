from __future__ import annotations

import gzip
from collections import Counter
from pathlib import Path

import pytest
from conftest import healthy, starving, ticks

from underfed.detector import Thresholds
from underfed.replay import run

QUICK = Thresholds(ratio=0.70, confirm_seconds=45, warmup_seconds=60, stable_seconds=180)
EIGHT_SEPTEMBER = Path(__file__).parent / "fixtures" / "delaybuf-2026-09-07-08.log.gz"
STARVED_FEEDS = {"202096.ts", "94281.ts", "202121.ts", "202099.ts"}
STARVED_AT_1757 = "272355.ts"


@pytest.mark.parametrize(
    ("stable_seconds", "triggers", "feeds"),
    [(0, 45, STARVED_FEEDS), (180, 79, STARVED_FEEDS | {STARVED_AT_1757})],
)
def test_the_evening_of_8_september_triggers_only_on_the_starved_feeds(
    tmp_path: Path, stable_seconds: int, triggers: int, feeds: set[str]
):
    log = tmp_path / "delaybuf.log"
    log.write_bytes(gzip.decompress(EIGHT_SEPTEMBER.read_bytes()))
    thresholds = Thresholds(
        ratio=0.70, confirm_seconds=45, warmup_seconds=60, stable_seconds=stable_seconds
    )
    outcome = run(log, thresholds)
    per_feed = Counter(hit.feed for hit in outcome.hits)
    assert len(outcome.feeds) == 26
    assert set(per_feed) == feeds
    assert sum(per_feed.values()) == triggers


def test_the_feed_caught_at_17_57_was_feeding_the_player_below_half_the_content_rate(
    tmp_path: Path,
):
    log = tmp_path / "delaybuf.log"
    log.write_bytes(gzip.decompress(EIGHT_SEPTEMBER.read_bytes()))
    hits = [hit for hit in run(log, Thresholds()).hits if hit.feed == STARVED_AT_1757]
    assert len(hits) == 1
    assert hits[0].percent < 60
    lines = [
        line for line in log.read_text().splitlines()
        if f"[{STARVED_AT_1757}]" in line and "cushion=0s" in line
    ]
    assert len(lines) >= 4


def write(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "delaybuf.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_a_quiet_log_reports_no_triggers(tmp_path: Path):
    outcome = run(write(tmp_path, ticks(0, 40, healthy)), QUICK)
    assert outcome.hits == []
    assert outcome.samples == 40
    assert "nothing would have been switched" in outcome.summary()


def test_a_starving_source_is_named_in_the_summary(tmp_path: Path):
    lines = ticks(0, 5, healthy) + ticks(5, 6, starving)
    outcome = run(write(tmp_path, lines), QUICK)
    assert [hit.feed for hit in outcome.hits] == ["202121.ts"]
    assert "202121.ts" in outcome.summary()
    assert "23%" in outcome.summary()


def test_noise_between_telemetry_lines_is_skipped(tmp_path: Path):
    lines = ticks(0, 5, healthy) + ["upstream EOF", "upstream connected edge=x.lol"]
    lines += ticks(5, 6, starving)
    outcome = run(write(tmp_path, lines), QUICK)
    assert outcome.lines == len(lines)
    assert outcome.samples == 11
    assert len(outcome.hits) == 1


def test_a_log_without_telemetry_says_so(tmp_path: Path):
    outcome = run(write(tmp_path, ["nothing", "useful"]), QUICK)
    assert outcome.samples == 0
    assert "No telemetry" in outcome.summary()


def test_a_missing_file_is_reported_not_swallowed(tmp_path: Path):
    try:
        run(tmp_path / "absent.log", QUICK)
    except FileNotFoundError as error:
        assert "absent.log" in str(error)
    else:
        raise AssertionError("a missing log should raise")


def test_a_stricter_threshold_finds_more(tmp_path: Path):
    lines = ticks(0, 5, healthy) + [
        starving(tick).replace("in=1.00Mbps", "in=3.40Mbps") for tick in range(5, 12)
    ]
    path = write(tmp_path, lines)
    lenient = run(path, QUICK)
    strict = run(path, Thresholds(ratio=0.90, confirm_seconds=45, warmup_seconds=60))
    assert lenient.hits == []
    assert strict.hits != []
