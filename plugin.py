from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

try:
    from .underfed import process
    from .underfed import state as state_module
    from .underfed.constants import (
        API_KEY_ENV,
        DEFAULT_API_URL,
        DEFAULT_TELEMETRY_PATH,
        HEARTBEAT_INTERVAL_SECONDS,
        MAX_RECENT_EVENTS,
        PLUGIN_DESCRIPTION,
        PLUGIN_NAME,
        PLUGIN_VERSION,
    )
    from .underfed.detector import Thresholds
    from .underfed.journal import Journal
    from .underfed.replay import run as replay
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from underfed import process
    from underfed import state as state_module
    from underfed.constants import (
        API_KEY_ENV,
        DEFAULT_API_URL,
        DEFAULT_TELEMETRY_PATH,
        HEARTBEAT_INTERVAL_SECONDS,
        MAX_RECENT_EVENTS,
        PLUGIN_DESCRIPTION,
        PLUGIN_NAME,
        PLUGIN_VERSION,
    )
    from underfed.detector import Thresholds
    from underfed.journal import Journal
    from underfed.replay import run as replay

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / ".runtime"
STATE_PATH = RUNTIME_DIR / "state.json"
JOURNAL_PATH = RUNTIME_DIR / "underfed.jsonl"
LOG_PATH = RUNTIME_DIR / "watcher.log"

DETACHING_REASONS = frozenset({"disable", "delete"})
ACTED_EVENTS = frozenset({"switched", "would_switch"})
FAILED_EVENTS = frozenset({"failed", "api_error"})

_heartbeat_lock = threading.Lock()
_heartbeat_checked_at = 0.0


def _read_manifest() -> dict[str, Any]:
    try:
        with (BASE_DIR / "plugin.json").open(encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


_MANIFEST = _read_manifest()


def _running_inside_uwsgi() -> bool:
    try:
        import uwsgi  # noqa: F401
    except ImportError:
        return False
    return True


def _as_number(value: object, fallback: float) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return fallback


def _as_text(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _lines(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        candidates = [str(item) for item in value]
    else:
        candidates = str(value).splitlines()
    return [item.strip() for item in candidates if item.strip()]


class Plugin:
    name = _MANIFEST.get("name", PLUGIN_NAME)
    version = _MANIFEST.get("version", PLUGIN_VERSION)
    description = _MANIFEST.get("description", PLUGIN_DESCRIPTION)
    author = _MANIFEST.get("author", "")
    help_url = _MANIFEST.get("help_url", "")
    fields = _MANIFEST.get("fields", [])
    actions = _MANIFEST.get("actions", [])

    def run(self, action: str, params: dict, context: dict) -> dict:
        handlers = {
            "apply": self._apply,
            "status": self._status,
            "test": self._test,
            "restart": self._restart,
            "remove": self._remove,
        }
        handler = handlers.get((action or "").strip().lower())
        if handler is None:
            return {"status": "error", "message": f"Unknown action '{action}'."}
        try:
            return handler(dict(context or {}))
        except Exception as exc:
            logger.exception("Underfed action '%s' failed", action)
            return {"status": "error", "message": f"{type(exc).__name__}: {exc}"}

    def stop(self, context: dict | None = None) -> dict:
        context = dict(context or {})
        stopped = self._stop_watcher()
        if str(context.get("reason") or "") in DETACHING_REASONS:
            self._remember({}, clear=["pid", "token", "signature", "applied"])
        else:
            self._remember({}, clear=["pid", "token"])
        return {
            "status": "ok",
            "message": "Watcher stopped." if stopped else "Watcher was not running.",
        }

    def _apply(self, context: dict) -> dict:
        settings = dict(context.get("settings") or {})
        key = _as_text(settings.get("api_key"), "")
        if not key:
            return {"status": "error", "message": "An API key is required."}

        telemetry = _as_text(settings.get("telemetry_path"), DEFAULT_TELEMETRY_PATH)
        if not Path(telemetry).is_file():
            return {
                "status": "error",
                "message": f"{telemetry} does not exist. Is reservoarr the stream profile?",
            }

        arguments = self._arguments(settings)
        signature = json.dumps(arguments, sort_keys=True)
        state = self._state()
        if process.is_running(state.get("pid"), state.get("token")):
            if state.get("signature") == signature:
                return {"status": "ok", "message": self._running_message(settings)}
            process.terminate(state.get("pid"), state.get("token"))

        self._start(arguments, key)
        self._remember({"signature": signature, "applied": True})
        return {"status": "ok", "message": self._running_message(settings)}

    def _running_message(self, settings: dict) -> str:
        percent = int(_as_number(settings.get("ratio_percent"), 70))
        seconds = int(_as_number(settings.get("confirm_seconds"), 45))
        mode = (
            "Observing only: it records what it would switch and changes nothing."
            if settings.get("observe_only", True)
            else "Switching is live."
        )
        return f"Watcher running below {percent}% of content rate for {seconds}s. {mode}"

    def _status(self, context: dict) -> dict:
        settings = dict(context.get("settings") or {})
        state = self._state()
        running = process.is_running(state.get("pid"), state.get("token"))
        records = Journal(JOURNAL_PATH, MAX_RECENT_EVENTS).read()
        acted = [row for row in records if row.get("event") in ACTED_EVENTS]
        skipped = [row for row in records if row.get("event") == "skipped"]
        failed = [row for row in records if row.get("event") in FAILED_EVENTS]

        if not state.get("applied"):
            headline = "Not applied yet. Fill in the API key and press Apply."
        else:
            headline = "Watcher is running." if running else "Watcher is not running."

        recent = "; ".join(self._describe(row) for row in acted[-5:])
        detail = f" Last: {recent}." if recent else " Nothing switched yet."
        if failed:
            detail += f" {len(failed)} error(s) in the journal."

        return {
            "status": "ok" if running or not state.get("applied") else "error",
            "message": f"{headline}{detail}",
            "running": running,
            "observe_only": bool(settings.get("observe_only", True)),
            "switched": len([row for row in acted if row.get("event") == "switched"]),
            "would_switch": len([row for row in acted if row.get("event") == "would_switch"]),
            "skipped": len(skipped),
            "events": records[-MAX_RECENT_EVENTS:],
        }

    def _describe(self, record: dict) -> str:
        verb = "switched" if record.get("event") == "switched" else "would switch"
        channel = record.get("channel") or record.get("feed")
        return f"{channel} {verb} at {record.get('percent')}%"

    def _test(self, context: dict) -> dict:
        settings = dict(context.get("settings") or {})
        telemetry = Path(_as_text(settings.get("telemetry_path"), DEFAULT_TELEMETRY_PATH))
        outcome = replay(telemetry, self._thresholds(settings))
        return {
            "status": "ok",
            "message": outcome.summary(),
            "samples": outcome.samples,
            "sources": len(outcome.feeds),
            "triggers": len(outcome.hits),
        }

    def _restart(self, context: dict) -> dict:
        settings = dict(context.get("settings") or {})
        state = self._state()
        if not state.get("applied"):
            return {"status": "ok", "message": "Nothing to do: not applied."}
        if not _running_inside_uwsgi():
            return {
                "status": "ok",
                "message": "Skipped: the watcher only starts in the Dispatcharr web process.",
            }
        if not self._heartbeat_due():
            return {"status": "ok", "message": "Checked recently."}
        if process.is_running(state.get("pid"), state.get("token")):
            return {"status": "ok", "message": "Watcher is running."}
        key = _as_text(settings.get("api_key"), "")
        if not key:
            return {"status": "error", "message": "An API key is required."}
        self._start(self._arguments(settings), key)
        return {"status": "ok", "message": "Watcher restarted."}

    def _remove(self, context: dict) -> dict:
        stopped = self._stop_watcher()
        self._remember({}, clear=["pid", "token", "applied", "signature"])
        return {
            "status": "ok",
            "message": "Watcher stopped." if stopped else "Watcher was not running.",
        }

    def _thresholds(self, settings: dict) -> Thresholds:
        percent = min(max(_as_number(settings.get("ratio_percent"), 70), 1.0), 99.0)
        return Thresholds(
            ratio=percent / 100,
            confirm_seconds=max(_as_number(settings.get("confirm_seconds"), 45), 5.0),
            warmup_seconds=max(_as_number(settings.get("warmup_seconds"), 60), 0.0),
            stable_seconds=max(_as_number(settings.get("stable_seconds"), 180), 0.0),
        )

    def _arguments(self, settings: dict) -> list[str]:
        arguments = [
            "--telemetry",
            _as_text(settings.get("telemetry_path"), DEFAULT_TELEMETRY_PATH),
            "--api-url",
            _as_text(settings.get("api_url"), DEFAULT_API_URL),
            "--journal",
            str(JOURNAL_PATH),
            "--ratio-percent",
            str(_as_number(settings.get("ratio_percent"), 70)),
            "--confirm-seconds",
            str(_as_number(settings.get("confirm_seconds"), 45)),
            "--warmup-seconds",
            str(_as_number(settings.get("warmup_seconds"), 60)),
            "--stable-seconds",
            str(_as_number(settings.get("stable_seconds"), 180)),
            "--max-switches",
            str(int(_as_number(settings.get("max_switches"), 2))),
        ]
        for name in _lines(settings.get("exclude_channels")):
            arguments += ["--exclude", name]
        if settings.get("observe_only", True):
            arguments.append("--observe-only")
        return arguments

    def _start(self, arguments: list[str], api_key: str) -> None:
        process.terminate_strays()
        token = uuid.uuid4().hex
        pid = process.spawn(
            BASE_DIR, arguments, token, LOG_PATH, extra_env={API_KEY_ENV: api_key}
        )
        self._remember({"pid": pid, "token": token, "started_at": time.time()})
        if not self._settled(pid, token):
            process.terminate(pid)
            self._remember({}, clear=["pid", "token"])
            raise RuntimeError(f"The watcher exited on startup. See {LOG_PATH}.")

    def _settled(self, pid: int, token: str, seconds: float = 3.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not process.is_running(pid, token):
                return False
            time.sleep(0.25)
        return True

    def _stop_watcher(self) -> bool:
        state = self._state()
        stopped = process.terminate(state.get("pid"), state.get("token"))
        strays = process.terminate_strays()
        return stopped or bool(strays)

    def _heartbeat_due(self) -> bool:
        global _heartbeat_checked_at
        now = time.monotonic()
        with _heartbeat_lock:
            if now - _heartbeat_checked_at < HEARTBEAT_INTERVAL_SECONDS:
                return False
            _heartbeat_checked_at = now
        return True

    def _state(self) -> dict:
        return state_module.load(STATE_PATH)

    def _remember(self, updates: dict, clear: list[str] | None = None) -> dict:
        return state_module.remember(STATE_PATH, updates, clear or [])
