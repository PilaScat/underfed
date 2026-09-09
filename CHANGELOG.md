# Changelog

## 0.1.0

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
