# Changelog

## 0.3.0 — 2026-09-14

- A source that starves in the middle of a session is caught about a minute sooner. The
  ingest is now the difference of reservoarr's `in_total` over the last 45 seconds instead of
  its `in`, which is a two-minute average: after a sharp drop `in` needed about 50 seconds to
  fall under 70% of `crate`, so with the 45-second confirmation the switch came some 100
  seconds after the drop. `in` still decides for the first 30 seconds of a feed, after the
  counter goes back (a new reservoarr process) and on lines without the counter; the
  journal's `measure` says which of the two decided.
- On the reference evening of 7-8 September the triggers stay on the four starved feeds at
  Stable after 0 (45, was 44) and reach one more at the default 180: 272355 at 17:57, which had
  the cushion empty and fed the player 1.64 of 4.6 Mbps while `in` still read 3.6 (79, was 58).
  On every telemetry line since 30 August the first trigger of each known episode comes
  between 0 and 894 seconds sooner: 336 seconds on Sky Sport 252 on 10 September, 272 on
  202121 on 8 September.
- A channel created after the watcher last read the chains is looked up again when it
  starves, at most once a minute. Before, it was skipped with "no source after this one"
  for up to 15 minutes.

## 0.2.1 — 2026-09-14

- Restart watcher, by hand or on a channel start, uses the settings of the last Apply, as
  the README always said. Before, a setting saved but not applied went live at the next
  channel start.
- Observe-only counts toward Switches per hour, so its would_switch lines match what live
  mode would do instead of repeating every 45 seconds.
- The channel and stream lists are read page by page. Before, only the first page was read,
  so past 500 channels or 9000 streams the watcher skipped with "no source after this one".
- The log reader notices a file replaced under the same inode, which Linux allows, instead
  of reading it from the middle.
- The evening of 8 September is a test: its telemetry is a fixture, and the replay must
  find 44 triggers at Stable after 0 and 58 at 180, only on the four starved feeds.
- The README says what Replay counts and when the warm-up starts. Tests, types, lint and
  build run in CI; `docs/MEMORY.md` holds the decisions, the deployment traps and the
  release routine.

## 0.2.0 — 2026-09-14

- Stable after now counts. A shortfall ends only once the source has held up that long,
  so a source flickering between 40% and 80% no longer restarts the confirmation window
  every time it rises. A line whose content rate is not trustworthy neither starts nor ends
  a shortfall. At 0 it behaves as 0.1.0 did.
- Over the reservoarr log from 30 August to 13 September, Replay finds 51 triggers at 0 and
  67 at the default 180, every extra one on a source that already triggered and none on the
  healthy ones. On flickering episodes the first trigger comes earlier, by 91 and 96
  seconds on the two worst evenings.
- The watcher survives an unexpected error: it is recorded in the journal, once while it
  repeats, and Check status counts it. Before, anything but an API error stopped the watcher
  until the next channel started.
- The logo and the README changes made after 0.1.0 are in the release zip.
- Checked against Dispatcharr 0.31.0: nothing the plugin relies on changed.

## 0.1.0 — 2026-09-09

First release.

- Follows the reservoarr telemetry log and compares the bytes arriving from the provider
  (`in`) against the bitrate the picture needs (`crate`).
- Moves the channel to the next source in its chain when a source stays below the threshold
  with the cushion empty, which is the one failure no other watchdog reacts to: the stream
  never stops, so nothing fires.
- Guards: a warm-up window, a per-channel limit on switches per hour, only channels with
  clients, never onto the fallback slate.
- Observe-only mode records what it would have done and changes nothing.
- Replay runs the thresholds over an existing log so a change can be checked before it goes live.
