from __future__ import annotations

from conftest import STEP_SECONDS, healthy, line, starving, ticks

from underfed.detector import Detector, Thresholds
from underfed.telemetry import parse

QUICK = Thresholds(ratio=0.70, confirm_seconds=45, warmup_seconds=60, stable_seconds=180)
WARM = 5


def feed(detector: Detector, lines: list[str]) -> list:
    verdicts = []
    for text in lines:
        sample = parse(text)
        assert sample is not None
        verdict = detector.observe(sample)
        if verdict is not None:
            verdicts.append(verdict)
    return verdicts


def test_a_healthy_source_never_triggers():
    assert feed(Detector(QUICK), ticks(0, 40, healthy)) == []


def test_a_starving_source_triggers_once_the_shortfall_is_confirmed():
    verdicts = feed(Detector(QUICK), ticks(0, WARM, healthy) + ticks(WARM, 4, starving))
    assert len(verdicts) == 1
    assert verdicts[0].feed == "202121.ts"
    assert verdicts[0].percent == 23


def test_nothing_triggers_before_the_shortfall_has_lasted_long_enough():
    lines = ticks(0, WARM, healthy) + ticks(WARM, 3, starving)
    assert feed(Detector(QUICK), lines) == []


def test_the_warm_up_window_suppresses_a_source_that_starts_bad():
    assert feed(Detector(QUICK), ticks(0, 4, starving)) == []


def test_a_source_that_recovers_and_starves_again_triggers_twice():
    lines = (
        ticks(0, WARM, healthy)
        + ticks(WARM, 4, starving)
        + ticks(WARM + 4, 14, healthy)
        + ticks(WARM + 18, 4, starving)
    )
    assert len(feed(Detector(QUICK), lines)) == 2


def test_a_recovery_shorter_than_stable_after_does_not_restart_the_count():
    lines = (
        ticks(0, WARM, healthy)
        + ticks(WARM, 3, starving)
        + ticks(WARM + 3, 2, healthy)
        + ticks(WARM + 5, 1, starving)
    )
    verdicts = feed(Detector(QUICK), lines)
    assert len(verdicts) == 1
    assert verdicts[0].seconds == 5 * 15


def test_a_recovery_that_lasts_stable_after_restarts_the_count():
    lines = (
        ticks(0, WARM, healthy)
        + ticks(WARM, 3, starving)
        + ticks(WARM + 3, 13, healthy)
        + ticks(WARM + 16, 1, starving)
    )
    assert feed(Detector(QUICK), lines) == []


def test_stable_after_at_zero_restarts_the_count_at_the_first_healthy_sample():
    at_once = Thresholds(ratio=0.70, confirm_seconds=45, warmup_seconds=60, stable_seconds=0)
    lines = (
        ticks(0, WARM, healthy)
        + ticks(WARM, 3, starving)
        + ticks(WARM + 3, 1, healthy)
        + ticks(WARM + 4, 1, starving)
    )
    assert feed(Detector(at_once), lines) == []


def test_a_sample_without_a_trustworthy_content_rate_does_not_restart_the_count():
    lines = (
        ticks(0, WARM, healthy)
        + ticks(WARM, 3, starving)
        + [line(tick, cushion=0, inbound=0.1, crate=0.2) for tick in range(WARM + 3, WARM + 5)]
        + ticks(WARM + 5, 1, starving)
    )
    assert len(feed(Detector(QUICK), lines)) == 1


def test_a_continuing_shortfall_repeats_at_the_confirmation_interval():
    verdicts = feed(Detector(QUICK), ticks(0, WARM, healthy) + ticks(WARM, 30, starving))
    assert len(verdicts) > 1
    gaps = [b.at - a.at for a, b in zip(verdicts, verdicts[1:], strict=False)]
    assert all(gap >= QUICK.confirm_seconds for gap in gaps)


def test_a_full_cushion_is_not_a_shortfall_even_when_ingest_dips():
    lines = ticks(0, WARM, healthy) + [
        line(tick, cushion=20, inbound=1.0) for tick in range(WARM, WARM + 20)
    ]
    assert feed(Detector(QUICK), lines) == []


def test_a_source_just_under_the_threshold_still_triggers():
    lines = ticks(0, WARM, healthy) + [
        line(tick, cushion=0, inbound=3.1, crate=4.44) for tick in range(WARM, WARM + 6)
    ]
    assert len(feed(Detector(QUICK), lines)) == 1


def test_a_source_just_over_the_threshold_is_left_alone():
    lines = ticks(0, WARM, healthy) + [
        line(tick, cushion=0, inbound=3.2, crate=4.44) for tick in range(WARM, WARM + 20)
    ]
    assert feed(Detector(QUICK), lines) == []


def test_an_untrustworthy_content_rate_is_ignored():
    lines = ticks(0, WARM, healthy) + [
        line(tick, cushion=0, inbound=0.1, crate=0.2) for tick in range(WARM, WARM + 20)
    ]
    assert feed(Detector(QUICK), lines) == []


def test_a_gap_in_the_log_restarts_the_warm_up():
    lines = ticks(0, WARM, healthy) + ticks(100, 4, starving)
    assert feed(Detector(QUICK), lines) == []


def test_two_sources_are_judged_apart():
    detector = Detector(QUICK)
    lines: list[str] = []
    for tick in range(0, WARM):
        lines += [healthy(tick), healthy(tick, feed="94281.ts")]
    for tick in range(WARM, WARM + 4):
        lines += [healthy(tick), starving(tick, feed="94281.ts")]
    assert [verdict.feed for verdict in feed(detector, lines)] == ["94281.ts"]


def test_the_snapshot_reports_each_source_it_has_seen():
    detector = Detector(QUICK)
    lines = ticks(0, WARM, healthy) + ticks(WARM, 4, starving)
    feed(detector, lines)
    last = parse(lines[-1])
    assert last is not None
    rows = detector.snapshot(now=last.at)
    assert [row["feed"] for row in rows] == ["202121.ts"]
    assert rows[0]["percent"] == 23
    assert rows[0]["starving_for"] is not None


def counted(start: int, count: int, inbound_by_counter: float, total: float, **kwargs) -> list:
    rows = []
    for index in range(count):
        total += inbound_by_counter * STEP_SECONDS / 8
        rows.append(line(start + index, total=round(total), **kwargs))
    return rows


def test_the_ingest_comes_from_the_lifetime_counter_once_it_spans_thirty_seconds():
    detector = Detector(QUICK)
    lines = counted(0, 6, 4.4, 1000, cushion=28, inbound=4.4)
    lines += counted(6, 3, 1.0, 1000 + 6 * 4.4 * STEP_SECONDS / 8, cushion=0, inbound=4.0)
    feed(detector, lines)
    state = detector.feeds["202121.ts"]
    assert state.measure == "in_total"
    assert state.ingest_mbps < 2.5


def test_a_drop_the_average_hides_triggers_from_the_counter():
    base = 1000 + WARM * 4.4 * STEP_SECONDS / 8
    lines = counted(0, WARM, 4.4, 1000, cushion=28, inbound=4.4)
    lines += counted(WARM, 7, 1.0, base, cushion=0, inbound=4.0)
    verdicts = feed(Detector(QUICK), lines)
    assert len(verdicts) == 1
    assert verdicts[0].measure == "in_total"
    assert verdicts[0].percent < 60


def test_the_same_drop_read_off_the_average_alone_is_missed():
    lines = ticks(0, WARM, healthy) + [
        line(tick, cushion=0, inbound=4.0) for tick in range(WARM, WARM + 7)
    ]
    assert feed(Detector(QUICK), lines) == []


def test_a_counter_that_goes_back_means_a_new_process_and_the_average_holds_meanwhile():
    lines = counted(0, WARM, 4.4, 1000, cushion=28, inbound=4.4)
    lines += [line(WARM, cushion=0, inbound=1.0, total=12)]
    detector = Detector(QUICK)
    feed(detector, lines)
    state = detector.feeds["202121.ts"]
    assert state.measure == "in"
    assert state.ingest_mbps == 1.0


def test_a_steady_counter_at_the_content_rate_never_triggers():
    lines = counted(0, 40, 4.44, 1000, cushion=0, inbound=1.0)
    assert feed(Detector(QUICK), lines) == []


def test_the_snapshot_says_which_measure_it_used():
    detector = Detector(QUICK)
    lines = counted(0, 4, 4.4, 1000, cushion=28, inbound=4.4)
    feed(detector, lines)
    last = parse(lines[-1])
    assert last is not None
    row = detector.snapshot(now=last.at)[0]
    assert row["measure"] == "in_total"
    assert abs(row["in_mbps"] - 4.4) < 0.3


def test_thresholds_come_from_the_plugin_settings():
    thresholds = Thresholds.from_settings(
        {"ratio_percent": "80", "confirm_seconds": "30", "warmup_seconds": "0"}
    )
    assert thresholds.ratio == 0.8
    assert thresholds.confirm_seconds == 30
    assert thresholds.warmup_seconds == 0


def test_nonsense_settings_fall_back_instead_of_raising():
    thresholds = Thresholds.from_settings({"ratio_percent": "", "confirm_seconds": "abc"})
    assert 0 < thresholds.ratio < 1
    assert thresholds.confirm_seconds >= 5
