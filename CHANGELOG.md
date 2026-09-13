# Changelog

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
