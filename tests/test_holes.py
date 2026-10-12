from __future__ import annotations

from conftest import healthy, holed, muted, ticks

from underfed.detector import Thresholds
from underfed.holes import HolesDetector
from underfed.telemetry import parse

RULE = Thresholds(holes_percent=10, holes_confirm_seconds=30, warmup_seconds=60)


def feed(detector: HolesDetector, lines: list[str]) -> list:
    found = []
    for text in lines:
        sample = parse(text)
        assert sample is not None
        verdict = detector.observe(sample)
        if verdict is not None:
            found.append(verdict)
    return found


def test_half_the_video_missing_triggers_after_warmup_and_confirmation():
    found = feed(HolesDetector(RULE), ticks(0, 6, holed))
    assert len(found) == 1
    assert found[0].feed == "542062.ts"
    assert found[0].percent == 50
    assert found[0].at - found[0].since == 60


def test_a_source_holed_after_the_warmup_triggers_after_thirty_seconds():
    lines = ticks(0, 8, healthy, feed="542062.ts")
    lines = [text + " vholes=0% aholes=0%" for text in lines] + ticks(8, 3, holed)
    found = feed(HolesDetector(RULE), lines)
    assert len(found) == 1
    assert found[0].seconds == 30


def test_a_line_under_the_threshold_resets_the_count():
    lines = ticks(0, 6, holed)[:5] + [ticks(5, 1, holed, percent=5)[0]] + ticks(6, 2, holed)
    found = feed(HolesDetector(RULE), lines)
    assert [verdict.at for verdict in found] == [found[0].at]
    assert found[0].since == parse(lines[0]).at


def test_a_short_burst_does_not_trigger():
    lines = [text + " vholes=0% aholes=0%" for text in ticks(0, 8, healthy, feed="542062.ts")]
    lines += ticks(8, 2, holed)
    lines += [text + " vholes=0% aholes=0%" for text in ticks(10, 4, healthy, feed="542062.ts")]
    assert feed(HolesDetector(RULE), lines) == []


def test_lines_without_the_field_are_ignored():
    assert feed(HolesDetector(RULE), ticks(0, 10, healthy)) == []


def test_zero_turns_the_rule_off():
    assert feed(HolesDetector(Thresholds(holes_percent=0)), ticks(0, 10, holed)) == []


def test_a_lasting_source_is_reported_again_only_after_another_confirmation():
    found = feed(HolesDetector(RULE), ticks(0, 12, holed))
    gaps = [b.at - a.at for a, b in zip(found, found[1:], strict=False)]
    assert len(found) >= 2
    assert all(gap >= RULE.holes_confirm_seconds for gap in gaps)


def test_the_defaults_are_ten_percent_for_thirty_seconds():
    defaults = Thresholds()
    assert defaults.holes_percent == 10
    assert defaults.holes_confirm_seconds == 30


def test_the_settings_are_read_and_kept_in_range():
    thresholds = Thresholds.from_settings({"holes_percent": "150", "holes_confirm_seconds": "1"})
    assert thresholds.holes_percent == 100
    assert thresholds.holes_confirm_seconds == 5
    assert Thresholds.from_settings({"holes_percent": "x"}).holes_percent == 10


def test_sound_alone_missing_triggers_and_says_so():
    found = feed(HolesDetector(RULE), ticks(0, 6, muted))
    assert len(found) == 1
    assert found[0].what == "audio"
    assert found[0].audio_percent == 100
    assert found[0].video_percent == 0
    assert "sound" in found[0].describe()


def test_picture_alone_missing_says_so():
    found = feed(HolesDetector(RULE), ticks(0, 6, holed, audio=0))
    assert found[0].what == "video"
    assert "picture" in found[0].describe()


def test_both_missing_says_so():
    found = feed(HolesDetector(RULE), ticks(0, 6, holed))
    assert found[0].what == "both"
    assert found[0].percent == 50
