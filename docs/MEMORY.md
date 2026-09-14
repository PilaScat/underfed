# Underfed — working notes

Decisions, traps and the release routine. What the plugin does for a user is in the
[README](../README.md).

## Decisions

- **The signal is ingest against `crate`** in reservoarr's `delaybuf.log`: what the provider
  sends against what the picture needs. Dispatcharr's own buffering failover reads ffmpeg's
  `speed=`, which is an average since the tune, so a feed that starves an hour in never drops
  below 0.9. `/proxy/ts/status` has the bitrate but not `crate`, so the file stays the source.
- **Ingest is the `in_total` difference over 45 s** (0.3.0), not `in`: reservoarr averages
  `in` over 120 s (`RATE_WINDOW_S`), and after a sharp drop it crossed 70% only ~50 s later;
  with the 45 s confirmation the switch came ~100 s after the drop. `in_total` is whole MB, so
  the window needs at least 30 s (±0.18 Mbps); before that, after a counter that goes back (a
  new reservoarr process) and on lines without it, `in` is used. The journal's `measure` says
  which one decided.
- **Thresholds**: below 70% of `crate` with `cushion=0` for 45 s, after a 60 s warm-up, at most
  2 switches an hour per channel. A shortfall ends only after Stable after (180 s) of recovery,
  so a flickering source is still caught (0.2.0). Lines with `crate` under 0.5 Mbps are ignored.
- **The reference evening** is 7-8 September 2026 (UTC), kept in
  `tests/fixtures/delaybuf-2026-09-07-08.log.gz`: 45 triggers at Stable after 0, all on 202096,
  94281, 202121 and 202099; 79 at 180, one of them on 272355 at 17:57, which had the cushion
  empty and fed the player 1.64 of 4.6 Mbps while `in` still read 3.6 (0.2.1 found 44 and 58,
  on the four only). Retune only with that test and a replay of a fresh log. Replay counts
  triggers, not switches.
- **The watcher is a detached process** without Django, talking to Dispatcharr over HTTP.
  `restart` is bound to `channel_start` and starts it with the arguments of the last Apply,
  stored in `.runtime/state.json` as `signature`.

## Traps

- Dispatcharr passes `params` to `run()`, never in `context`, and only the events in
  `apps/connect/models.py:SUPPORTED_EVENTS` reach a plugin (19 in 0.31.0).
- The tailer compares the first bytes of the log as well as `(device, inode)`: on Linux a file
  replaced in place can keep its inode.
- `next_stream` goes through even with the provider at its connection limit when the channel is
  already on that M3U profile.
- Importing a zip with `overwrite=true` replaces the folder, `.runtime/` included: copy it out
  and back. Reload after the import, then Apply, since the reload stops every plugin's watcher.

## Release

1. Version in `plugin.json`, `underfed/constants.py` and `pyproject.toml`.
2. A `CHANGELOG.md` section, written before the tag.
3. `python scripts/build_zip.py`, then an annotated tag `vX.Y.Z` named `Underfed X.Y.Z`.
4. A GitHub Release with the CHANGELOG text, the list of commits it contains, and the zip.
5. Not in the `Dispatcharr/Plugins` registry yet.
