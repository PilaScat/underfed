from __future__ import annotations

from pathlib import Path

from conftest import healthy, starving, ticks

from underfed.detector import Thresholds
from underfed.replay import run

QUICK = Thresholds(ratio=0.70, confirm_seconds=45, warmup_seconds=60, stable_seconds=180)


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
