from __future__ import annotations

from conftest import STEP_SECONDS, healthy, starving

from underfed.telemetry import parse, parse_all, parse_discontinuity

REAL = (
    "2026-09-08T20:18:57+0000 [202121.ts] cushion=0s(pcr) buf=0.1MB out=1.18Mbps "
    "in=1.00Mbps crate=4.44Mbps in_total=1589MB reconnects=2 ccerr=1 pcrrej=0 "
    "disc=1 sync=1 pcr_back=0"
)
VIDEO_JUMP = (
    "2026-09-14T17:35:25+0000 [542059.ts] ffmpeg: [vist#0:0/h264 @ 0x55c7ee1ac2c0] "
    "timestamp discontinuity (stream id=256): 331826689, new offset= 0"
)
AUDIO_JUMP = (
    "2026-09-14T17:35:25+0000 [542059.ts] ffmpeg: [aist#0:1/aac @ 0x55c7ee1abdc0] "
    "timestamp discontinuity (stream id=257): -331826689, new offset= 331826689"
)


def test_a_real_telemetry_line_is_read_field_by_field():
    sample = parse(REAL)
    assert sample is not None
    assert sample.feed == "202121.ts"
    assert sample.cushion_seconds == 0
    assert sample.clock == "pcr"
    assert sample.in_mbps == 1.00
    assert sample.crate_mbps == 4.44
    assert sample.out_mbps == 1.18
    assert sample.reconnects == 2


def test_the_shortfall_is_the_ratio_of_arriving_bits_to_needed_bits():
    sample = parse(REAL)
    assert sample is not None
    assert round(sample.ratio, 3) == 0.225


def test_a_byte_clock_cushion_is_read_too():
    sample = parse(REAL.replace("(pcr)", "(byte)"))
    assert sample is not None
    assert sample.clock == "byte"


def test_lines_that_are_not_telemetry_are_ignored():
    assert parse("2026-09-08T20:19:57+0000 [202121.ts] upstream EOF") is None
    assert parse("") is None
    assert parse("garbage") is None


def test_a_missing_reconnects_counter_reads_as_zero():
    trimmed = REAL.split(" in_total=")[0]
    sample = parse(trimmed)
    assert sample is not None
    assert sample.reconnects == 0
    assert sample.total_mb is None


def test_the_lifetime_ingest_counter_is_read():
    sample = parse(REAL)
    assert sample is not None
    assert sample.total_mb == 1589


def test_timestamps_carry_their_offset():
    first = parse(healthy(5))
    second = parse(healthy(6))
    assert first is not None and second is not None
    assert second.at - first.at == STEP_SECONDS


def test_parse_all_keeps_only_telemetry():
    lines = [healthy(1), "upstream connected edge=x.lol", starving(2)]
    assert len(parse_all(lines)) == 2


def test_a_timestamp_discontinuity_is_read_on_video_and_on_audio():
    video = parse_discontinuity(VIDEO_JUMP)
    audio = parse_discontinuity(AUDIO_JUMP)
    assert video is not None and audio is not None
    assert video.feed == audio.feed == "542059.ts"
    assert video.at == audio.at


def test_other_lines_are_not_timestamp_discontinuities():
    assert parse_discontinuity(REAL) is None
    assert parse_discontinuity(
        "2026-09-14T18:46:49+0000 [542059.ts] ffmpeg: [aost#0:1/ac3 @ 0x556161d6dd80] "
        "Non-monotonic DTS; previous: 330000, current: 327120; changing to 330001."
    ) is None
    assert parse_discontinuity("garbage") is None


def test_a_timestamp_discontinuity_is_not_telemetry():
    assert parse(VIDEO_JUMP) is None
