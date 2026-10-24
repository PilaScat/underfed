from __future__ import annotations

PLUGIN_NAME = "Underfed"
PLUGIN_VERSION = "0.9.0"
PLUGIN_DESCRIPTION = (
    "Moves a channel off a source that is starving it, drifting its sound, missing whole "
    "stretches, looping on corrupt packets or refusing it: to the next source when the stream "
    "arrives at a fraction of its bitrate, with its timestamps apart, with holes in its picture "
    "or sound or forcing reconnect after reconnect, to the back "
    "of the chain when the provider answers 403 or closes the connection without sending a "
    "byte."
)

WATCHER_MODULE = "underfed.watcher"
RUN_TOKEN_ENV = "UNDERFED_RUN_TOKEN"
API_KEY_ENV = "UNDERFED_API_KEY"

DEFAULT_TELEMETRY_PATH = "/data/scripts/logs/delaybuf.log"
DEFAULT_API_URL = "http://127.0.0.1:9191"

DEFAULT_RATIO_PERCENT = 70
DEFAULT_CONFIRM_SECONDS = 45
DEFAULT_STORM_CONFIRM_SECONDS = 15
DEFAULT_MAX_SWITCHES_PER_HOUR = 2
DEFAULT_WARMUP_SECONDS = 60
DEFAULT_STABLE_SECONDS = 180
DEFAULT_STORM_PER_MINUTE = 100
DEFAULT_DEMOTE_MINUTES = 30
DEFAULT_HOLES_PERCENT = 10
DEFAULT_HOLES_CONFIRM_SECONDS = 30
DEFAULT_LOOPS_COUNT = 3
DEFAULT_LOOPS_MINUTES = 5

CAUSE_UNDERFED = "underfed"
CAUSE_TIMESTAMPS = "timestamps"
CAUSE_FORBIDDEN = "forbidden"
CAUSE_EMPTY = "empty"
CAUSE_HOLES = "holes"
CAUSE_LOOPS = "loops"

MIN_TRUSTED_CRATE_MBPS = 0.5
STORM_WINDOW_SECONDS = 60.0
SAMPLE_GAP_TOLERANCE_SECONDS = 45.0
INGEST_WINDOW_SECONDS = 45.0
INGEST_MIN_SPAN_SECONDS = 30.0

POLL_INTERVAL_SECONDS = 2.0
MAPPING_REFRESH_SECONDS = 900.0
API_TIMEOUT_SECONDS = 10.0
TERMINATE_GRACE_SECONDS = 10.0
HEARTBEAT_INTERVAL_SECONDS = 60.0

MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_RECENT_EVENTS = 50
