from __future__ import annotations

from conftest import discontinuity, storm

from underfed.detector import Thresholds
from underfed.storm import StormDetector
from underfed.telemetry import parse_discontinuity

RULE = Thresholds(confirm_seconds=45, storm_per_minute=100)


def feed(detector: StormDetector, lines: list[str]) -> list:
    storms = []
    for text in lines:
        jump = parse_discontinuity(text)
        assert jump is not None
        found = detector.observe(jump)
        if found is not None:
            storms.append(found)
    return storms


def every(seconds: int, lines_each: int, until: int) -> list[str]:
    return [
        discontinuity(second)
        for second in range(0, until, seconds)
        for _ in range(lines_each)
    ]


def test_a_storm_triggers_once_it_has_lasted_the_confirmation():
    storms = feed(StormDetector(RULE), storm(0, 50))
    assert len(storms) == 1
    assert storms[0].feed == "542059.ts"
    assert storms[0].seconds == 45
    assert storms[0].per_minute >= 100


def test_nothing_triggers_before_the_confirmation():
    assert feed(StormDetector(RULE), storm(0, 40)) == []


def test_the_handful_a_healthy_source_logs_never_triggers():
    assert feed(StormDetector(RULE), every(9, 1, 3600)) == []


def test_a_rate_under_the_threshold_is_left_alone():
    assert feed(StormDetector(RULE), every(2, 3, 600)) == []


def test_a_rate_over_the_threshold_triggers():
    assert feed(StormDetector(RULE), every(1, 2, 600)) != []


def test_zero_turns_the_rule_off():
    off = Thresholds(confirm_seconds=45, storm_per_minute=0)
    assert feed(StormDetector(off), storm(0, 300)) == []


def test_a_continuing_storm_repeats_at_the_confirmation_interval():
    storms = feed(StormDetector(RULE), storm(0, 300))
    assert len(storms) > 1
    gaps = [b.at - a.at for a, b in zip(storms, storms[1:], strict=False)]
    assert all(gap >= RULE.confirm_seconds for gap in gaps)


def test_a_quiet_spell_starts_the_count_over():
    assert feed(StormDetector(RULE), storm(0, 30) + storm(200, 30)) == []


def test_two_sources_are_judged_apart():
    lines: list[str] = []
    for second in range(0, 60):
        lines += storm(second, 1)
        if second % 10 == 0:
            lines.append(discontinuity(second, feed="542040.ts"))
    assert {found.feed for found in feed(StormDetector(RULE), lines)} == {"542059.ts"}


def test_the_verdict_says_how_bad_it_was():
    found = feed(StormDetector(RULE), storm(0, 50))[0]
    assert "timestamp discontinuities a minute" in found.describe()
    assert "542059.ts" in found.describe()
