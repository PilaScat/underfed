# Changelog

## 0.8.0 — 2026-10-12

- **A source missing whole stretches of picture or sound is moved to the next source.** On
  12 October 2026 a source arrived at full rate (`in=2.07Mbps crate=2.05Mbps`) while dropping
  4 seconds out of every 8, picture and sound: the viewer saw lag and the sound out of sync, and
  neither the shortfall nor the discontinuities noticed. A reservoarr that measures it reports
  the share of each window the picture and the sound are missing as `vholes=N% aholes=N%` at
  the end of its telemetry line, sound that stops while the picture runs included; the change
  is proposed to reservoarr for 6.3.9 and is not in a release yet. Two new settings,
  **Picture or sound missing** (10%) and **Confirm missing picture or sound for** (30 s): when
  every line of a source reads that share or more, for either of the two, for that long, after
  the warm-up, the channel moves to the next source, within the same switches per hour. The
  journal records it as `cause: holes`, with both shares and `what` (`video`, `audio` or
  `both`). Without those fields, as with reservoarr 6.3.8, nothing changes. **Replay the
  log** counts these triggers too.

## 0.7.0 — 2026-10-11

- **A source that closes the connection without sending a byte goes to the back of its chain**,
  like a source the provider answers 403 to, and for the same minutes (Refused source held back).
  The sign is reservoarr's `giving up` right after an `upstream EOF`. On the evening of 10 October
  2026 an edge accepted the connection and closed it about twenty seconds later; Dispatcharr
  retried it three times, about 43 seconds, and six viewers in a row waited between 23 and 50
  seconds each for the same channel. The provider's MP4 placeholder, a 407 and a 520 are not
  counted: they say the channel is off air, the provider is full or the VPN is refused, not that
  the source is broken. The journal tells the two causes apart: `forbidden` and `empty`.

## 0.6.0 — 2026-10-07

- **A timestamp storm is confirmed after 15 seconds**, with its own setting, **Confirm
  discontinuities for**. Up to 0.5.0 it waited Confirm for, 45 s, like a shortfall. On
  6 October 2026 a fallback feed logged 324 timestamp discontinuities a minute for 44 s, with
  the picture running fast and the sound drifting, and the viewer gave up one second before the
  switch. Replayed on the evening of 14 September, the 15 s confirmation still triggers only on
  the broken feed, 30 s earlier than before. Confirm for stays at 45 s and now applies to the
  shortfall only.
- The fallback import block of `plugin.py` imports the default of Refused source held back,
  which it was missing.

## 0.5.0 — 2026-09-21

- **A source the provider refuses goes to the back of its chain.** Dispatcharr forgets a refused
  source with the session, so the next tune-in starts on it again and pays the same wait: over
  five days of logs, 192 episodes of `HTTP 403`, 154 ending in a give-up, and 32 sources out of
  53 refused more than once — one of them eighteen times. Now one refusal moves the source last
  in the chain, ahead of the fallback card, and it climbs back to its old position after
  **Refused source held back** minutes (30 by default, 0 to turn it off). Both moves are in the
  journal, as `demoted` and `restored`.
- The demotions live in `.runtime/demotions.json` and survive a restart of the watcher: a
  source held back is held back for the whole window, not until the next Apply.
- Before restoring, the watcher re-reads the catalogue rather than trusting the copy it has:
  with a stale one the restore did nothing and the demotion was dropped in silence.

## 0.4.0 — 2026-09-15

- A source whose audio and video timestamps are far apart is switched too. reservoarr's ffmpeg
  then corrects every packet and swallows the gaps in the video, so the sound falls further
  behind with each one: on 14 September it was 7.8 s out after 20 minutes, and a viewer
  reopened the channel eight times. The sign is the `timestamp discontinuity` lines in
  `delaybuf.log`. At Timestamp discontinuities or above, per minute and 100 by default, for
  Confirm for, the channel moves to its next source with the guards and the hourly limit of a
  starving one. 0 turns it off.
- From 5 to 15 September healthy feeds never logged more than 7 of those lines a minute. Replay
  over those days finds 60 triggers, all on the feed of 14 September, the first 45 s after its
  first packet; a 6-second burst on 9 September stays under the confirmation. The shortfall
  triggers are the same 103 with the rule and without it.
- On a test bench, a source with its audio timestamps 300 s from its video made reservoarr log
  770 of those lines a minute, and the watcher moved the channel to its healthy source 47 s after
  the first one, without passing through the slate. The healthy source and a control channel
  logged none and were left alone.
- Replay counts the two causes apart, Check status names the cause of each switch, and the
  journal carries it as `cause`.

## 0.3.2 — 2026-09-14

- The hourly switch limit holds across a restart of the watcher. The switches of the last
  hour lived only in memory, so an Apply, a plugin reload or a restart of Dispatcharr let a
  channel be switched again at once, past Switches per hour. They are now kept in
  `.runtime/switches.json` and read back when the watcher starts. The review of the registry
  submission found it.
- README: a manual install unzips the release into `/data/plugins`, since the archive holds
  the `underfed` folder; Restart watcher reads the API key as saved, not as applied; a typo
  in the Trigger below row.

## 0.3.1 — 2026-09-14

- A watcher started within 15 minutes of the host booting reads the channel chains at once.
  It measured their age from a monotonic clock that starts at boot, with zero as "never
  read", so on a fresh host the first read waited until the clock passed 15 minutes, and
  until then every starving channel was skipped with "no source after this one". The CI
  runners, freshly booted, showed it in the 0.3.0 tests.

## 0.3.0 — 2026-09-14

- A source that starves in the middle of a session is caught sooner. The ingest is now the
  difference of reservoarr's `in_total` over the last 45 seconds instead of its `in`, which is
  a two-minute average: after a sharp drop `in` needed about 50 seconds to fall under 70% of
  `crate`, so Dispatcharr's own failover got there first, 105 seconds after the drop on the
  test bench. With 0.3.0 Underfed switched the same feed, dropped to 30%, 79 seconds after the
  drop: the cushion takes about 25 of them to run out, the confirmation 45. `in` still decides for the first 30 seconds of a feed, after the
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
