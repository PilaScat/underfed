from __future__ import annotations

from conftest import corrupt_loop

from underfed.detector import Thresholds
from underfed.loops import LoopDetector
from underfed.telemetry import parse_corrupt_loop

RULE = Thresholds(loops_count=3, loops_minutes=5)


def feed(detector: LoopDetector, lines: list[str]) -> list:
    found = []
    for text in lines:
        loop = parse_corrupt_loop(text)
        assert loop is not None
        verdict = detector.observe(loop)
        if verdict is not None:
            found.append(verdict)
    return found


def test_the_third_loop_within_five_minutes_triggers():
    found = feed(LoopDetector(RULE), [corrupt_loop(0), corrupt_loop(105), corrupt_loop(160)])
    assert len(found) == 1
    assert found[0].feed == "198329.ts"
    assert found[0].count == 3
    assert found[0].seconds == 160


def test_two_loops_are_left_alone():
    assert feed(LoopDetector(RULE), [corrupt_loop(0), corrupt_loop(60)]) == []


def test_three_loops_spread_over_six_minutes_are_left_alone():
    lines = [corrupt_loop(0), corrupt_loop(180), corrupt_loop(360)]
    assert feed(LoopDetector(RULE), lines) == []


def test_loops_exactly_five_minutes_apart_still_count():
    lines = [corrupt_loop(0), corrupt_loop(150), corrupt_loop(300)]
    assert len(feed(LoopDetector(RULE), lines)) == 1


def test_loops_on_different_sources_do_not_add_up():
    lines = [corrupt_loop(0, feed="a.ts"), corrupt_loop(10, feed="b.ts"), corrupt_loop(20)]
    assert feed(LoopDetector(RULE), lines) == []


def test_after_a_trigger_the_count_starts_over():
    lines = [corrupt_loop(second) for second in (0, 30, 60, 90, 120)]
    assert len(feed(LoopDetector(RULE), lines)) == 1


def test_zero_turns_the_rule_off():
    off = Thresholds(loops_count=0, loops_minutes=5)
    assert feed(LoopDetector(off), [corrupt_loop(second) for second in range(0, 60, 5)]) == []
