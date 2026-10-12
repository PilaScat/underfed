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
  A 30 s confirmation was tried on the replay of the logs since 30 August 2026: about 15 s
  earlier on real starvation, but it also fired on dips that heal on their own within 15-30 s,
  healthy reference feeds included. Every switch costs a hitch and one of the two an hour, so it
  stays 45 s.
- **The reference evening** is 7-8 September 2026 (UTC), kept in
  `tests/fixtures/delaybuf-2026-09-07-08.log.gz`: 45 triggers at Stable after 0, all on 202096,
  94281, 202121 and 202099; 79 at 180, one of them on 272355 at 17:57, which had the cushion
  empty and fed the player 1.64 of 4.6 Mbps while `in` still read 3.6 (0.2.1 found 44 and 58,
  on the four only). Retune only with that test and a replay of a fresh log. Replay counts
  triggers, not switches.
- **Timestamp discontinuities** (0.4.0): a source whose audio and video timestamps are far apart
  makes reservoarr's ffmpeg correct every packet, which swallows the video's gaps and leaves the
  sound behind, 7.8 s after 20 minutes on 14 September 2026. The signal is the `timestamp
  discontinuity` lines of a feed over the last 60 s: from 5 to 15 September healthy feeds never
  logged more than 7 a minute, the broken ones 648 (for 6 s) and 1,000-1,836 (for 73 minutes).
  The threshold is 100, on by default, and there is no warm-up: the storm starts with the first
  packet. A count under the threshold ends it at once. The reference is
  `tests/fixtures/delaybuf-2026-09-14.log.gz`, the telemetry and discontinuity lines from 17:30
  to 17:50 UTC: 47 triggers, all on 542059, the first at 17:35:40.
- **A storm has its own confirmation, 15 s** (0.6.0, chosen by the operator on 7 October 2026).
  Up to 0.5.0 it shared Confirm for (45 s) with the shortfall. On 6 October a fallback feed
  stormed at 324 lines a minute for 44 s and the viewer left one second before the switch.
  The shortfall keeps 45 s: the CDN delivers in bursts of about ten seconds, and there is no
  measure of shorter false alarms. On the 14 September replay the 15 s confirmation still
  triggers only on the broken feed.
- **The watcher is a detached process** without Django, talking to Dispatcharr over HTTP.
  `restart` is bound to `channel_start` and starts it with the arguments of the last Apply,
  stored in `.runtime/state.json` as `signature`; the API key is read from the saved settings.
- **The hourly limit survives a restart** (0.3.2): the watcher keeps the switches of the last
  hour in `.runtime/switches.json`, not in the journal, which is trimmed to 50 lines.

- **A refusal rewrites the chain, not the session** (0.5.0). The other two failures move the
  viewer with `next_stream`; this one changes the order of the channel's sources, because the
  point is the *next* tune-in, which starts from the top again — `tried_stream_ids` dies with
  the session. The refused source goes last among the sources, never after the fallback card:
  Could Not Dispatch keeps that one at the end and would put it back anyway.
- **One refusal is enough, and it climbs back after thirty minutes** (numbers from the
  operator, on five days of logs: 192 refusal episodes, median 6 s but 140 s at the ninth
  decile; of 135 returns on the same source, 43 within ten minutes and 60 within half an hour).
- **A source that closes without data is demoted like a refusal** (0.7.0, chosen by the operator
  on 11 October 2026: one failure, thirty minutes, the same setting). The trigger is a `giving up`
  whose previous upstream line for that feed is `upstream EOF`. On 10 October, between 18:44 and
  18:51 UTC, `542034.ts` hung ~20 s and closed four times, while its MP4 placeholder and the 407s of
  its siblings made 82 more give-ups that must not count: an MP4 means nothing is on air (every
  source of a DAZN Web channel answers with it, 151 that day), a 407 or 520 is the provider or the
  VPN. The replay is `tests/fixtures/delaybuf-2026-10-10.log.gz`: one demotion, on `542034.ts`.
- **Missing picture or sound** (0.8.0, numbers chosen by the operator on 12 October 2026: 10%
  for 30 s, after the 60 s warm-up, one setting for both, the worse of the two counts). That day `542062.ts` arrived at full rate (`in=2.07 crate=2.05`)
  while dropping 4 s out of every 8: 732 audio packets and 584 frames in 49 s of output instead
  of ~1,540 and ~1,230. No other rule sees it: the PCR jumps with the content, the jumps stay
  under ffmpeg's 10 s threshold, `speed=` stays at 1.0. The signal is reservoarr's
  `vholes=N% aholes=N%` (6.3.9, measured in the parser on the incoming PES timestamps, so the
  silence of `RESV_AUDIO_FILL_GAPS` does not hide it), not a probe of Dispatcharr's output: no
  extra client, no sampling. Healthy feeds read 0/0; the bench fixtures with 4 s in 8 missing
  read 35-52 (picture) and 46-51 (sound) per window, sound stopping reads 100. AAC decoder
  errors were looked at and left out: 36 lines in 18 days, at most 9 in a minute. Without the
  fields (older reservoarr) the rule is silent. There is no replay
  fixture yet: the first production log with `vholes=` becomes it.
- **The restore re-reads the catalogue.** With the cached copy, a chain already reordered made
  `restored_order` return "nothing to do" and the demotion was dropped without the source ever
  climbing back. The state lives in `.runtime/demotions.json`, so a restart does not lose it.

## Traps

- Dispatcharr passes `params` to `run()`, never in `context`, and only the events in
  `apps/connect/models.py:SUPPORTED_EVENTS` reach a plugin (20 in 0.32.0).
- The tailer compares the first bytes of the log as well as `(device, inode)`: on Linux a file
  replaced in place can keep its inode.
- "Never" is `-inf`, not 0, next to `time.monotonic()`: the monotonic clock starts at boot, so
  for the first 15 minutes after a host restart a 0 looked recent and the chains were never read
  (fixed in 0.3.1).
- `next_stream` goes through even with the provider at its connection limit when the channel is
  already on that M3U profile.
- Importing a zip with `overwrite=true` replaces the folder, `.runtime/` included: copy it out
  and back. Reload after the import, then Apply, since the reload stops every plugin's watcher.

## Release

1. Version in `plugin.json`, `underfed/constants.py` and `pyproject.toml`.
2. A `CHANGELOG.md` section, written before the tag.
3. `python scripts/build_zip.py`, then an annotated tag `vX.Y.Z` named `Underfed X.Y.Z`.
4. A GitHub Release with the CHANGELOG text, the list of commits it contains, and the zip.
5. Publishing the Release starts `.github/workflows/registry-pr.yml`, which opens the PR to
   `Dispatcharr/Plugins` from the `PilaScat/Plugins` fork: the version in
   `plugins/underfed/plugin.json`, the README next to it when it changed, and the CHANGELOG
   section as the description. It needs the `REGISTRY_PR_TOKEN` secret, a classic PAT of
   PilaScat with `public_repo` only; it can be rerun by hand with the tag. The registry
   installs the zip at `source_url`, so a README change reaches users only with a new version.
