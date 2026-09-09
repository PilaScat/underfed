from __future__ import annotations

from pathlib import Path

from underfed.journal import Journal


def test_events_come_back_in_the_order_they_were_written(tmp_path: Path):
    journal = Journal(tmp_path / "j.jsonl", 10)
    journal.write("switched", channel="Sky | Sport Uno", percent=23)
    journal.write("skipped", reason="no clients")
    records = journal.read()
    assert [row["event"] for row in records] == ["switched", "skipped"]
    assert records[0]["channel"] == "Sky | Sport Uno"


def test_a_missing_file_reads_as_no_events(tmp_path: Path):
    assert Journal(tmp_path / "absent.jsonl", 10).read() == []


def test_the_file_is_trimmed_instead_of_growing_without_end(tmp_path: Path):
    path = tmp_path / "j.jsonl"
    journal = Journal(path, 5)
    for index in range(60):
        journal.write("tick", index=index)
    kept = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(kept) <= 20
    assert journal.read()[-1]["index"] == 59


def test_a_corrupt_line_does_not_lose_the_rest(tmp_path: Path):
    path = tmp_path / "j.jsonl"
    journal = Journal(path, 10)
    journal.write("switched")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    journal.write("skipped")
    assert [row["event"] for row in journal.read()] == ["switched", "skipped"]
