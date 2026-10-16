"""Debug session: attach/ping/BP/step/eval over HTTP Debug Protocol."""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from adapters.debug_http import xml_build, xml_parse
from adapters.debug_http.client import DebugHttpClient, HttpResponse
from adapters.debug_http.constants import (
    CODE_MODULE_UNRESOLVED,
    CODE_NO_SESSION,
    CODE_NO_TARGETS,
    CODE_NOT_STOPPED,
    CODE_WAIT_TIMEOUT,
    DEFAULT_ALIAS,
    DEFAULT_ATTACH_RETRIES,
    DEFAULT_AUTO_ATTACH_TYPES,
    DEFAULT_PING_INTERVAL_SEC,
    DEFAULT_WAIT_TIMEOUT_SEC,
    EVAL_ASYNC_WAIT_SEC,
    PING_HTTP_TIMEOUT_SEC,
    SOURCE_DEBUG,
)
from adapters.debug_http.errors import DebugHttpError
from adapters.debug_http.models import (
    AttachResult,
    BreakpointSpec,
    DebugEvent,
    DebugTarget,
    EvalResult,
    ModuleRef,
    StackFrame,
    StopEvent,
)
from adapters.debug_http.resolve import ObjectIdResolver, StubObjectIdResolver
from core.diagnostics import error as diag_error


class DebugSession:
    """Stateful debug UI session against one ``dbgs`` instance.

    Ping loop runs in-process (~500 ms). Inject ``XmlObjectIdResolver`` for
    module UUID resolve from XML source (#139); default is stub (tests).
    """

    def __init__(
        self,
        client: DebugHttpClient,
        *,
        alias: str = DEFAULT_ALIAS,
        session_id: str | None = None,
        ping_interval: float = DEFAULT_PING_INTERVAL_SEC,
        resolver: ObjectIdResolver | None = None,
        auto_attach_types: Sequence[str] | None = None,
    ) -> None:
        self.client = client
        self.alias = alias
        self.session_id = session_id or str(uuid.uuid4())
        self.ping_interval = ping_interval
        self.resolver: ObjectIdResolver = resolver or StubObjectIdResolver()
        self.auto_attach_types: tuple[str, ...] = tuple(
            auto_attach_types or DEFAULT_AUTO_ATTACH_TYPES
        )

        self._attached = False
        self._breakpoints: list[BreakpointSpec] = []
        self._attached_targets: set[str] = set()
        self._last_stop: StopEvent | None = None
        self._last_target_id: str = ""

        #: ``(result_id, timeout) -> body`` for results delivered via ping
        #: (``exprEvaluated``) instead of the POST body; set by the CLI layer.
        self.eval_result_reader: Callable[[str, float], str | None] | None = None

        self._events: deque[DebugEvent] = deque()
        self._events_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._ping_thread: threading.Thread | None = None
        self._ping_stop = threading.Event()

    # --- session lifecycle -------------------------------------------------

    @property
    def attached(self) -> bool:
        return self._attached

    @property
    def last_stop(self) -> StopEvent | None:
        return self._last_stop

    @property
    def last_target_id(self) -> str:
        return self._last_target_id

    @property
    def attached_targets(self) -> frozenset[str]:
        """Targets this session has attached (snapshot copy)."""
        return frozenset(self._attached_targets)

    @property
    def breakpoints(self) -> tuple[BreakpointSpec, ...]:
        """Breakpoints held by the session (snapshot copy)."""
        return tuple(self._breakpoints)

    # --- state restore across processes --------------------------------------

    def mark_attached(self) -> None:
        """Mark the session as attached without sending ``attachDebugUI``.

        For processes that continue a session attached by another process
        (short-lived CLI, ping daemon) using ``session.json``.
        """
        self._attached = True

    def restore_state(
        self,
        *,
        attached_targets: Iterable[str] | None = None,
        last_target_id: str | None = None,
        breakpoints: Sequence[BreakpointSpec] | None = None,
        last_stop: StopEvent | None = None,
    ) -> None:
        """Hydrate in-memory state from persisted data; nothing is sent to ``dbgs``.

        ``None`` leaves the corresponding part untouched. A restored ``last_stop``
        wins over a stale ``last_target_id`` (stopped target is authoritative).
        """
        if attached_targets is not None:
            self._attached_targets = set(attached_targets)
        if last_target_id:
            self._last_target_id = last_target_id
        if breakpoints is not None:
            self._breakpoints = list(breakpoints)
        if last_stop is not None:
            self._last_stop = last_stop
            self._stop_event.set()
            if last_stop.target_id:
                self._attached_targets.add(last_stop.target_id)
                self._last_target_id = last_stop.target_id

    def merge_attached_targets(self, target_ids: Iterable[str]) -> None:
        """Add targets known to be attached (e.g. by another process)."""
        self._attached_targets |= set(target_ids)

    def prune_attached_targets(self, target_ids: Iterable[str]) -> None:
        """Forget targets that are gone from ``getDbgAllTargetStates``."""
        self._attached_targets -= set(target_ids)

    def attach(
        self,
        *,
        password: str = "",
        max_retries: int = DEFAULT_ATTACH_RETRIES,
        start_ping: bool = True,
    ) -> AttachResult:
        """``attachDebugUI`` with ``ibInDebug`` detach+retry; then init + autoAttach."""
        last = ""
        attempts = 0
        for attempt in range(max_retries):
            attempts = attempt + 1
            resp = self.client.post(
                "attachDebugUI",
                xml_build.build_attach(self.alias, self.session_id, password),
            )
            last = xml_parse.extract_result(resp.body) or f"http={resp.status}"
            if last == "ibInDebug":
                self.client.post(
                    "detachDebugUI",
                    xml_build.build_detach(self.alias, self.session_id),
                )
                time.sleep(0.2)
                continue
            if last in ("notRegistered", "credentialsRequired", "fullCredentialsRequired"):
                raise DebugHttpError(
                    f"attach failed: {last}",
                    code=CODE_NO_SESSION,
                )
            # registered / empty / ok / numeric success
            if last in ("ibInDebug",):
                continue
            break
        else:
            raise DebugHttpError(
                f"ibInDebug after {max_retries} retries; last={last}",
                code=CODE_NO_SESSION,
            )

        self._attached = True
        self.client.post(
            "initSettings",
            xml_build.build_init_settings(self.alias, self.session_id, break_on_next=False),
        )
        self.client.post(
            "setAutoAttachSettings",
            xml_build.build_auto_attach(self.alias, self.session_id, self.auto_attach_types),
        )
        if self._breakpoints:
            self._send_breakpoints()
        if start_ping:
            self.start_ping()
        return AttachResult(session_id=self.session_id, result=last, attempts=attempts)

    def detach(self) -> str:
        """``detachDebugUI``; stop ping. Returns ``result`` text."""
        self.stop_ping()
        if not self._attached and not self.session_id:
            raise DebugHttpError("нет активной сессии", code=CODE_NO_SESSION)
        resp = self.client.post(
            "detachDebugUI",
            xml_build.build_detach(self.alias, self.session_id),
        )
        self._attached = False
        self._attached_targets.clear()
        return xml_parse.extract_result(resp.body)

    def force_detach(self) -> str:
        """Detach current UI and rotate ``session_id`` (recovery / zombie attach)."""
        result = ""
        try:
            result = self.detach()
        except DebugHttpError:
            self.stop_ping()
            self._attached = False
        self.session_id = str(uuid.uuid4())
        self._last_stop = None
        self._attached_targets.clear()
        return result

    # --- ping / events -----------------------------------------------------

    def start_ping(self) -> None:
        """Start in-process ping loop (~``ping_interval``)."""
        if self._ping_thread and self._ping_thread.is_alive():
            return
        self._ping_stop.clear()
        self._ping_thread = threading.Thread(
            target=self._ping_loop,
            name="debug-http-ping",
            daemon=True,
        )
        self._ping_thread.start()

    def stop_ping(self) -> None:
        """Stop ping loop and join the thread.

        Keep join short: ping may be blocked in HTTP; daemon thread will exit
        on process end. Long join made every ``attach``/``wait`` feel hung (~2s).
        """
        self._ping_stop.set()
        thread = self._ping_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.2)
        self._ping_thread = None

    def drain_events(self) -> list[DebugEvent]:
        """Pop all queued ping events."""
        with self._events_lock:
            items = list(self._events)
            self._events.clear()
        return items

    def process_ping_body(self, body: str, *, status: int = 200) -> list[DebugEvent]:
        """Handle one ping response (also used by the background loop / tests)."""
        if status == 400:
            # dbgs restarted — caller may force_detach + reattach; enqueue marker
            ev = DebugEvent(type="http400", raw_xml=body)
            self._enqueue(ev)
            return [ev]

        events = xml_parse.parse_ping_events(body)
        for ev in events:
            self._enqueue(ev)
            if ev.type == "targetStarted":
                tid = ev.target_id or self.extract_target_id(body)
                if tid:
                    self.attach_target(tid)
            if ev.type == "callStackFormed":
                stop = xml_parse.parse_stop_event(
                    body,
                    target_id=ev.target_id or self._last_target_id,
                )
                if stop is not None:
                    stop = StopEvent(
                        target_id=stop.target_id,
                        frames=self.enrich_frames(stop.frames),
                        raw_xml=stop.raw_xml,
                    )
                    self._last_stop = stop
                    if stop.target_id:
                        self._last_target_id = stop.target_id
                    self._stop_event.set()
        return events

    def enrich_frames(
        self, frames: tuple[StackFrame, ...] | list[StackFrame]
    ) -> tuple[StackFrame, ...]:
        """Fill ``moduleName``/``moduleType`` from XML index (reverse objectID lookup)."""
        index = getattr(self.resolver, "index", None)
        find_by_ids = getattr(index, "find_by_ids", None) if index is not None else None
        if find_by_ids is None:
            return tuple(frames)
        enriched: list[StackFrame] = []
        for frame in frames:
            if frame.module_name and frame.module_type and frame.extension_name:
                enriched.append(frame)
                continue
            hits = find_by_ids(frame.object_id, frame.property_id)
            if not hits and frame.object_id:
                hits = find_by_ids(frame.object_id, None)
            hit = hits[0] if hits else None
            enriched.append(
                StackFrame(
                    object_id=frame.object_id,
                    property_id=frame.property_id,
                    line_no=frame.line_no,
                    module_name=frame.module_name or (hit.module_name if hit else ""),
                    module_type=frame.module_type or (hit.module_type if hit else ""),
                    extension_name=frame.extension_name
                    or (hit.extension_name if hit else ""),
                )
            )
        return tuple(enriched)

    def _ping_loop(self) -> None:
        while not self._ping_stop.is_set():
            try:
                # ping is a ~5 s server long-poll: timeout must exceed it, else
                # events are consumed server-side and lost (spike #135 §5a).
                resp = self.client.post(
                    "pingDebugUIParams",
                    "",
                    dbgui=self.session_id,
                    timeout=PING_HTTP_TIMEOUT_SEC,
                )
                self.process_ping_body(resp.body, status=resp.status)
            except DebugHttpError as exc:
                if not exc.timeout:
                    self._enqueue(
                        DebugEvent(type="pingError", payload={"message": exc.message})
                    )
            self._ping_stop.wait(self.ping_interval)

    def _enqueue(self, event: DebugEvent) -> None:
        with self._events_lock:
            self._events.append(event)

    def attach_target(self, target_id: str, *, force: bool = False) -> None:
        """Attach one target (``attachDetachDbgTargets``) once and re-send breakpoints."""
        self._last_target_id = target_id
        if target_id in self._attached_targets and not force:
            return
        self.client.post(
            "attachDetachDbgTargets",
            xml_build.build_attach_targets(
                self.alias, self.session_id, [target_id], attach=True
            ),
        )
        self._attached_targets.add(target_id)
        # BP must be re-sent after target attach (spike / MIT)
        if self._breakpoints:
            self._send_breakpoints()

    def ensure_targets_attached(self, *, force: bool = False) -> list[DebugTarget]:
        """Attach known targets from ``getDbgAllTargetStates``.

        Short-lived CLI may miss ``targetStarted`` when the attach process exits
        and its ping loop dies; ``wait`` / BP then never arm on the client.
        """
        found = self.targets()
        for target in found:
            tid = target.target_id
            if tid:
                self.attach_target(tid, force=force)
        return found

    @staticmethod
    def extract_target_id(body: str) -> str:
        ids = xml_parse.find_texts(body, "id")
        for cand in ids:
            if len(cand) >= 32:
                return cand
        return ids[0] if ids else ""

    # --- targets / breakpoints ---------------------------------------------

    def require_attached(self) -> None:
        if not self._attached:
            raise DebugHttpError(
                "нет активной debug-сессии",
                code=CODE_NO_SESSION,
                diagnostics=[
                    diag_error(
                        "нет активной debug-сессии",
                        code=CODE_NO_SESSION,
                        source=SOURCE_DEBUG,
                        suggestion="выполните debug.attach",
                    )
                ],
            )

    def targets(self) -> list[DebugTarget]:
        """``getDbgAllTargetStates``."""
        self.require_attached()
        resp = self.client.post(
            "getDbgAllTargetStates",
            xml_build.request_xml(self.alias, self.session_id),
        )
        return xml_parse.parse_targets(resp.body)

    def set_breakpoints(self, modules: Sequence[BreakpointSpec]) -> None:
        """Store and send breakpoints (``setBreakpoints``)."""
        self.require_attached()
        self._breakpoints = list(modules)
        self._send_breakpoints()

    def clear_breakpoints(self) -> None:
        """Clear all breakpoints (empty ``bpWorkspace``)."""
        self.require_attached()
        self._breakpoints = []
        self._send_breakpoints()

    def set_breakpoints_by_module(
        self,
        module_name: str,
        module_type: str,
        lines: Sequence[int],
        *,
        extension_name: str | None = None,
    ) -> BreakpointSpec:
        """Resolve module via ``ObjectIdResolver`` then set BP."""
        ref = self.resolver.resolve(
            module_name, module_type, extension_name=extension_name
        )
        return self._apply_resolved_breakpoint(ref, lines, extension_name=extension_name)

    def set_breakpoints_by_file(
        self,
        bsl_path: str | Path,
        lines: Sequence[int],
        *,
        extension_name: str | None = None,
    ) -> BreakpointSpec:
        """Resolve ``.bsl`` path → objectID/propertyID then set BP (#145)."""
        resolve_file = getattr(self.resolver, "resolve_from_file", None)
        if resolve_file is None:
            raise DebugHttpError(
                "resolver не поддерживает resolve_from_file",
                code=CODE_MODULE_UNRESOLVED,
                diagnostics=[
                    diag_error(
                        "нужен XmlObjectIdResolver для --file",
                        code=CODE_MODULE_UNRESOLVED,
                        source=SOURCE_DEBUG,
                    )
                ],
            )
        ref = resolve_file(bsl_path, extension_name=extension_name)
        return self._apply_resolved_breakpoint(ref, lines, extension_name=extension_name)

    def set_breakpoints_by_ids(
        self,
        object_id: str,
        property_id: str,
        lines: Sequence[int],
        *,
        extension_name: str | None = None,
    ) -> BreakpointSpec:
        """Set BP with explicit objectID/propertyID (escape hatch #145)."""
        from adapters.debug_http.resolve import resolve_explicit_ids

        ref = resolve_explicit_ids(
            object_id, property_id, extension_name=extension_name or ""
        )
        return self._apply_resolved_breakpoint(ref, lines, extension_name=extension_name)

    def _apply_resolved_breakpoint(
        self,
        ref: ModuleRef,
        lines: Sequence[int],
        *,
        extension_name: str | None = None,
    ) -> BreakpointSpec:
        spec = BreakpointSpec(
            object_id=ref.object_id,
            property_id=ref.property_id,
            lines=tuple(lines),
            extension_name=ref.extension_name or (extension_name or ""),
        )
        remaining = [
            b
            for b in self._breakpoints
            if not (
                b.object_id == spec.object_id
                and b.property_id == spec.property_id
                and b.extension_name == spec.extension_name
            )
        ]
        self.set_breakpoints([*remaining, spec])
        return spec

    def _send_breakpoints(self) -> None:
        self.client.post(
            "setBreakpoints",
            xml_build.build_set_breakpoints(self.alias, self.session_id, self._breakpoints),
        )

    # --- wait / control ----------------------------------------------------

    def wait_for_stop(self, *, timeout: float = DEFAULT_WAIT_TIMEOUT_SEC) -> StopEvent:
        """Wait until ``callStackFormed`` (via ping loop) or timeout → ``1CD005``."""
        self.require_attached()
        # Already stopped (event set by process_ping_body / ping loop / disk hydrate)
        if self._last_stop is not None and self._stop_event.is_set():
            frames = self.enrich_frames(self._last_stop.frames)
            if frames != self._last_stop.frames:
                self._last_stop = StopEvent(
                    target_id=self._last_stop.target_id,
                    frames=frames,
                    raw_xml=self._last_stop.raw_xml,
                )
            return self._last_stop

        # Attach targets we have not seen yet (may have missed targetStarted).
        # Never force: re-attach of a stopped target breaks stepping (spike #135).
        self.ensure_targets_attached(force=False)

        self._stop_event.clear()
        self.start_ping()
        if not self._stop_event.wait(timeout):
            raise DebugHttpError(
                f"таймаут wait_for_stop ({timeout:g}s)",
                code=CODE_WAIT_TIMEOUT,
                diagnostics=[
                    diag_error(
                        f"таймаут ожидания остановки ({timeout:g}s)",
                        code=CODE_WAIT_TIMEOUT,
                        source=SOURCE_DEBUG,
                    )
                ],
            )
        if self._last_stop is None:
            raise DebugHttpError(
                "остановка получена без callStackFormed",
                code=CODE_WAIT_TIMEOUT,
            )
        return self._last_stop

    def continue_(self, target_id: str | None = None) -> str:
        return self._step("Continue", target_id)

    def step_in(self, target_id: str | None = None) -> str:
        return self._step("StepIn", target_id)

    def step_over(self, target_id: str | None = None) -> str:
        """Step over call (platform action ``Step`` — DAP next / EDT step over)."""
        return self._step("Step", target_id)

    def step_out(self, target_id: str | None = None) -> str:
        return self._step("StepOut", target_id)

    def pause(self) -> None:
        """``initSettings(breakOnNextLine=true)`` — smoke pause without module BP."""
        self.require_attached()
        self.client.post(
            "initSettings",
            xml_build.build_init_settings(self.alias, self.session_id, break_on_next=True),
        )

    def unpause(self) -> None:
        """Reset ``breakOnNextLine`` after a pause stop."""
        self.require_attached()
        self.client.post(
            "initSettings",
            xml_build.build_init_settings(self.alias, self.session_id, break_on_next=False),
        )

    def _step(self, action: str, target_id: str | None) -> str:
        self.require_attached()
        tid = target_id or self._require_target_id()
        self._stop_event.clear()
        resp = self.client.post(
            "step",
            xml_build.build_step(self.alias, self.session_id, tid, action),
        )
        return xml_parse.extract_result(resp.body)

    def _require_target_id(self) -> str:
        if self._last_target_id:
            return self._last_target_id
        if self._last_stop and self._last_stop.target_id:
            return self._last_stop.target_id
        known = list(self._attached_targets)
        if known:
            return known[0]
        raise DebugHttpError(
            "нет target для операции (клиент без HTTP /Debug?)",
            code=CODE_NO_TARGETS,
            diagnostics=[
                diag_error(
                    "нет debug-target",
                    code=CODE_NO_TARGETS,
                    source=SOURCE_DEBUG,
                    suggestion="runtime.start --debug с /Debug -http -attach + DebuggerURL",
                )
            ],
        )

    # --- inspection --------------------------------------------------------

    def stack(self, target_id: str | None = None) -> list[StackFrame]:
        """Stack frames from last stop (leaf = current)."""
        self.require_attached()
        if self._last_stop is None:
            raise DebugHttpError(
                "target не в stopped (нет callStackFormed)",
                code=CODE_NOT_STOPPED,
            )
        if target_id and self._last_stop.target_id and target_id != self._last_stop.target_id:
            raise DebugHttpError(
                f"last stop target={self._last_stop.target_id}, запрошен {target_id}",
                code=CODE_NOT_STOPPED,
            )
        frames = self.enrich_frames(self._last_stop.frames)
        if frames != self._last_stop.frames:
            self._last_stop = StopEvent(
                target_id=self._last_stop.target_id,
                frames=frames,
                raw_xml=self._last_stop.raw_xml,
            )
        return list(frames)

    def variables(self, target_id: str | None = None) -> EvalResult:
        """``evalLocalVariables`` (sync result in POST body on 8.3.25)."""
        self.require_attached()
        tid = target_id or self._require_stopped_target()
        result_id = str(uuid.uuid4())
        resp = self.client.post(
            "evalLocalVariables",
            xml_build.build_eval_locals(self.alias, self.session_id, tid, result_id),
        )
        self._raise_if_eval_http_error(resp, cmd="evalLocalVariables")
        return self._eval_result(resp.body, result_id)

    def evaluate(self, expression: str, target_id: str | None = None) -> EvalResult:
        """``evalExpr`` (sync result in POST body on 8.3.25)."""
        self.require_attached()
        tid = target_id or self._require_stopped_target()
        result_id = str(uuid.uuid4())
        resp = self.client.post(
            "evalExpr",
            xml_build.build_eval_expr(
                self.alias, self.session_id, tid, expression, result_id
            ),
        )
        self._raise_if_eval_http_error(resp, cmd="evalExpr")
        return self._eval_result(resp.body, result_id)

    def _eval_result(self, body: str, result_id: str) -> EvalResult:
        """Parse the POST body; if dbgs answered empty, take the ping-delivered one.

        dbgs routes the result to the pending ``pingDebugUIParams`` instead of the
        POST body when a ping long-poll is parked — which is always the case with
        the single-reader daemon.
        """
        parsed = xml_parse.parse_eval_result(body)
        if parsed.state or parsed.variables or self.eval_result_reader is None:
            return parsed
        late = self.eval_result_reader(result_id, EVAL_ASYNC_WAIT_SEC)
        return xml_parse.parse_eval_result(late) if late else parsed

    def _raise_if_eval_http_error(self, resp: HttpResponse, *, cmd: str) -> None:
        """HTTP 400 from dbgs must not look like «пустой список переменных»."""
        if resp.status < 400:
            return
        descr = xml_parse.extract_http_exception_descr(resp.body) or resp.body[:240]
        low = descr.lower()
        if "остановлен" in low or "stopped" in low:
            code = CODE_NOT_STOPPED
            suggestion = (
                "клиент не на точке останова (успели continue / промах BP / "
                "протухший lastStop) — runtime start --debug --bp … → debug wait"
            )
        elif "не зарегистрир" in low or "not registered" in low:
            code = CODE_NO_SESSION
            suggestion = "1c-dev debug attach (сессия UI на dbgs потеряна)"
        else:
            code = CODE_NOT_STOPPED
            suggestion = f"проверьте debug status / wait; ответ dbgs HTTP {resp.status}"
        raise DebugHttpError(
            f"{cmd} HTTP {resp.status}: {descr}",
            code=code,
            diagnostics=[
                diag_error(
                    f"{cmd}: {descr}",
                    code=code,
                    source=SOURCE_DEBUG,
                    suggestion=suggestion,
                )
            ],
        )

    def clear_cached_stop(self) -> None:
        """Drop in-memory last stop (for fresh ``wait`` after new client spawn)."""
        self._last_stop = None
        self._stop_event.clear()

    def _require_stopped_target(self) -> str:
        if self._last_stop is None:
            raise DebugHttpError(
                "target не в stopped",
                code=CODE_NOT_STOPPED,
                diagnostics=[
                    diag_error(
                        "target не в stopped — сначала wait_for_stop",
                        code=CODE_NOT_STOPPED,
                        source=SOURCE_DEBUG,
                    )
                ],
            )
        return self._last_stop.target_id or self._require_target_id()
