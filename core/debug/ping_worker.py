"""Detached debug daemon: the *only* ``pingDebugUIParams`` reader (ADR-031).

``pingDebugUIParams`` is a server-side long-poll (~5 s; events are delivered once
per request, spike #135 §5a). To not lose events there must be exactly one reader
with a client timeout above the long-poll. This daemon is that reader and also
the owner of target attach:

* ``targetStarted`` / periodic ``getDbgAllTargetStates`` → ``attachDetachDbgTargets``
  once per target + ``setBreakpoints`` from ``session.json``;
* ``callStackFormed`` → ``lastStop`` in ``session.json``.

CLI commands never ping; they read ``session.json`` (written under a lock).

Usage::

    python -m core.debug.ping_worker --root /path/to/project
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path
from typing import Any

from adapters.debug_http.client import DebugHttpClient
from adapters.debug_http.constants import (
    DEFAULT_PING_INTERVAL_SEC,
    PING_HTTP_TIMEOUT_SEC,
)
from adapters.debug_http.errors import DebugHttpError
from adapters.debug_http.session import DebugSession
from adapters.debug_http.xml_parse import find_texts, parse_ping_events, parse_stop_event
from core.debug.state import (
    breakpoints_from_stored,
    read_session,
    serialize_last_stop,
    update_session,
    write_eval_result,
)

MAX_CONSECUTIVE_ERRORS = 20
SCAN_INTERVAL_SEC = 0.5
SCAN_INTERVAL_ARMED_SEC = 1.5


def _log(message: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


def persist_stop_from_ping_body(root: Path, body: str) -> bool:
    """If ping body has ``callStackFormed``, write ``lastStop`` to session.json."""
    if not body or "callStackFormed" not in body:
        return False
    events = parse_ping_events(body)
    tid = ""
    for ev in events:
        if ev.type == "callStackFormed" and ev.target_id:
            tid = ev.target_id
            break
    stop = parse_stop_event(body, target_id=tid)
    if stop is None:
        return False
    payload = serialize_last_stop(stop)

    def _mutate(data: dict[str, Any]) -> dict[str, Any]:
        data["lastStop"] = payload
        if stop.target_id:
            data["lastTargetId"] = stop.target_id
            targets = {
                str(t)
                for t in (data.get("attachedTargets") or [])
                if isinstance(t, str) and t
            }
            targets.add(stop.target_id)
            data["attachedTargets"] = sorted(targets)
        return data

    return update_session(root, _mutate) is not None


class _Daemon:
    """Owns the debug UI side of one ``sessionId`` until the session goes away."""

    def __init__(self, root: Path, *, interval: float) -> None:
        self.root = root
        self.interval = max(0.02, interval)
        self.stop = threading.Event()
        self._attach_lock = threading.Lock()
        self.session_id = ""
        self.url = ""
        self.session: DebugSession | None = None

    def _bootstrap(self) -> bool:
        stored = read_session(self.root)
        if stored is None:
            return False
        url = stored.get("url")
        sid = stored.get("sessionId")
        if not isinstance(url, str) or not url.strip():
            return False
        if not isinstance(sid, str) or not sid.strip():
            return False
        self.url = url.rstrip("/")
        self.session_id = sid.strip()
        client = DebugHttpClient(self.url, timeout=PING_HTTP_TIMEOUT_SEC)
        session = DebugSession(
            client,
            alias=str(stored.get("alias") or "DefAlias"),
            session_id=self.session_id,
        )
        session._attached = True  # noqa: SLF001 — attached by the CLI process
        raw = stored.get("attachedTargets")
        if isinstance(raw, list):
            session._attached_targets = {  # noqa: SLF001
                str(t) for t in raw if isinstance(t, str) and t
            }
        self.session = session
        return True

    def _session_alive(self) -> bool:
        stored = read_session(self.root)
        return stored is not None and stored.get("sessionId") == self.session_id

    def _persist_targets(self) -> None:
        assert self.session is not None
        targets = sorted(self.session._attached_targets)  # noqa: SLF001

        def _mutate(data: dict[str, Any]) -> dict[str, Any] | None:
            if data.get("sessionId") != self.session_id:
                return None
            if targets:
                data["attachedTargets"] = targets
            else:
                data.pop("attachedTargets", None)
            return data

        update_session(self.root, _mutate)

    def attach_target(self, target_id: str) -> None:
        """Attach once; re-send breakpoints from disk (CLI may have changed them)."""
        assert self.session is not None
        with self._attach_lock:
            stored = read_session(self.root) or {}
            # A stop recorded for this target means it is attached already.
            disk_targets = stored.get("attachedTargets")
            if isinstance(disk_targets, list):
                self.session._attached_targets |= {  # noqa: SLF001
                    str(t) for t in disk_targets if isinstance(t, str) and t
                }
            if target_id in self.session._attached_targets:  # noqa: SLF001
                return
            self.session._breakpoints = breakpoints_from_stored(stored)  # noqa: SLF001
            self.session._on_target_started(target_id)  # noqa: SLF001
            self._persist_targets()
            _log(f"attached target {target_id}")

    def scan_targets(self) -> int:
        """``getDbgAllTargetStates`` → attach new, prune gone. Returns armed count."""
        assert self.session is not None
        found = self.session.targets()
        live = {t.target_id for t in found if t.target_id}
        for tid in sorted(live):
            self.attach_target(tid)
        with self._attach_lock:
            stale = self.session._attached_targets - live  # noqa: SLF001
            if stale:
                self.session._attached_targets -= stale  # noqa: SLF001
                self._persist_targets()
                _log(f"pruned targets {sorted(stale)}")
        return len(live)

    def _scanner(self) -> None:
        delay = SCAN_INTERVAL_SEC
        while not self.stop.wait(delay):
            try:
                armed = self.scan_targets()
                delay = SCAN_INTERVAL_ARMED_SEC if armed else SCAN_INTERVAL_SEC
            except DebugHttpError as exc:
                _log(f"scan error: {exc.message}")
                delay = SCAN_INTERVAL_ARMED_SEC
            except Exception as exc:  # noqa: BLE001 — scanner must not kill daemon
                _log(f"scan failure: {exc!r}")
                delay = SCAN_INTERVAL_ARMED_SEC

    def _store_eval_result(self, body: str) -> None:
        """evalExpr/evalLocalVariables answer may arrive via ping instead of POST."""
        ids = find_texts(body, "expressionResultID")
        if ids:
            write_eval_result(self.root, ids[0], body)
            _log(f"eval result stored {ids[0]}")

    def _handle_ping_body(self, body: str) -> None:
        assert self.session is not None
        events = parse_ping_events(body)
        if events:
            _log("ping events: " + ",".join(ev.type for ev in events))
            if "exprEvaluated" in body:
                self._store_eval_result(body)
        for ev in events:
            if ev.type == "targetStarted":
                tid = ev.target_id or DebugSession._extract_target_id(body)  # noqa: SLF001
                if tid:
                    try:
                        self.attach_target(tid)
                    except DebugHttpError as exc:
                        _log(f"attach error: {exc.message}")
        if persist_stop_from_ping_body(self.root, body):
            _log("stop persisted")

    def run(self) -> int:
        if not self._bootstrap():
            return 0
        assert self.session is not None
        _log(f"daemon start session={self.session_id} url={self.url}")
        scanner = threading.Thread(target=self._scanner, name="scan", daemon=True)
        scanner.start()
        errors = 0
        try:
            while True:
                if not self._session_alive():
                    _log("session gone — exit")
                    return 0
                try:
                    resp = self.session.client.post(
                        "pingDebugUIParams",
                        "",
                        dbgui=self.session_id,
                        timeout=PING_HTTP_TIMEOUT_SEC,
                    )
                    errors = 0
                    if resp.status == 200 and resp.body:
                        self._handle_ping_body(resp.body)
                except DebugHttpError as exc:
                    if exc.timeout:
                        continue  # long-poll overran — not a failure
                    errors += 1
                    _log(f"ping error {errors}: {exc.message}")
                    if errors >= MAX_CONSECUTIVE_ERRORS:
                        return 1
                    time.sleep(0.5)
                    continue
                except Exception as exc:  # noqa: BLE001 — keep daemon through faults
                    errors += 1
                    _log(f"ping failure {errors}: {exc!r}")
                    if errors >= MAX_CONSECUTIVE_ERRORS:
                        return 1
                    time.sleep(0.5)
                    continue
                time.sleep(self.interval)
        finally:
            self.stop.set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="1c-dev debug daemon (ping + attach)")
    parser.add_argument("--root", type=Path, required=True, help="Project root")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_PING_INTERVAL_SEC,
        help="Pause between successful pings (seconds)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        return _Daemon(root, interval=float(args.interval)).run()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
