"""Unit tests for adapters.debug_http (ADR-031 / #138) — mocks, no live platform."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from adapters.debug_http import (
    CODE_MODULE_UNRESOLVED,
    CODE_NO_SESSION,
    CODE_NOT_STOPPED,
    CODE_WAIT_TIMEOUT,
    DEFAULT_ALIAS,
    PROPERTY_ID_COMMON_MODULE,
    BreakpointSpec,
    DebugHttpClient,
    DebugHttpError,
    DebugSession,
    HttpResponse,
    ModuleRef,
    SourceRoot,
    StubObjectIdResolver,
    XmlObjectIdResolver,
    build_modules_index,
    xml_build,
    xml_parse,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "debug_http"
SPIKE_OBJECT_ID = "b7e2c4a1-8f3d-4a6e-9c1b-2d5e8f0a3b6c"
SPIKE_TARGET = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class MockTransport:
    """Record HTTP calls and return scripted responses by cmd."""

    def __init__(self, by_cmd: dict[str, list[HttpResponse] | HttpResponse]) -> None:
        self.by_cmd = {
            k: (v if isinstance(v, list) else [v]) for k, v in by_cmd.items()
        }
        self.calls: list[tuple[str, str, str | None]] = []  # cmd, body, dbgui

    def __call__(
        self,
        url: str,
        data: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> HttpResponse:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        cmd = qs.get("cmd", [""])[0]
        dbgui = qs.get("dbgui", [None])[0]
        body = data.decode("utf-8") if data else ""
        self.calls.append((cmd, body, dbgui))
        queue = self.by_cmd.get(cmd)
        if not queue:
            # empty ping by default
            if cmd == "pingDebugUIParams":
                return HttpResponse(200, "")
            return HttpResponse(200, "<response><result>1</result></response>")
        return queue.pop(0) if len(queue) > 1 else queue[0]


def test_build_attach_and_breakpoints_xml() -> None:
    xml = xml_build.build_attach(DEFAULT_ALIAS, "sid-1")
    assert "infoBaseAlias" in xml
    assert "idOfDebuggerUI" in xml
    assert "sid-1" in xml
    assert "&" not in xml_build.esc("a&b") or xml_build.esc("a&b") == "a&amp;b"

    bp = BreakpointSpec(
        object_id=SPIKE_OBJECT_ID,
        property_id=PROPERTY_ID_COMMON_MODULE,
        lines=(5,),
    )
    bp_xml = xml_build.build_set_breakpoints(DEFAULT_ALIAS, "sid-1", [bp])
    assert SPIKE_OBJECT_ID in bp_xml
    assert PROPERTY_ID_COMMON_MODULE in bp_xml
    assert "<line>5</line>" in bp_xml
    assert "bpWorkspace" in bp_xml


def test_esc_xml_special() -> None:
    assert xml_build.esc('<x>"&\'') == "&lt;x&gt;&quot;&amp;&apos;"


def test_parse_attach_and_stop_fixtures() -> None:
    assert xml_parse.extract_result(_load("attach_registered.xml")) == "registered"
    assert xml_parse.extract_result(_load("attach_ib_in_debug.xml")) == "ibInDebug"
    assert xml_parse.extract_result(_load("detach_ok.xml")) == "1"

    stop = xml_parse.parse_stop_event(_load("ping_call_stack.xml"))
    assert stop is not None
    assert len(stop.frames) == 2
    assert stop.current_frame is not None
    assert stop.current_frame.line_no == 5
    assert stop.current_frame.object_id == SPIKE_OBJECT_ID
    assert stop.line_no == 5

    events = xml_parse.parse_ping_events(_load("ping_target_started.xml"))
    types = {e.type for e in events}
    assert "targetStarted" in types


def test_parse_eval_fixtures() -> None:
    locals_res = xml_parse.parse_eval_result(_load("eval_locals.xml"))
    assert locals_res.ok
    assert locals_res.state == "correctly"
    names = [v.name for v in locals_res.variables]
    assert "Значение" in names
    assert "Результат" in names

    expr = xml_parse.parse_eval_result(_load("eval_expr.xml"))
    assert expr.state == "correctly"
    assert any(v.type_name == "Число" for v in expr.variables)
    assert expr.variables[0].presentation == "10"


def test_extract_http_exception_descr() -> None:
    body = (
        '<?xml version="1.0"?><exception reason="400">'
        "<descr>Выполнение вычислений возможно только в остановленном "
        "предмете отладки</descr></exception>"
    )
    assert "остановленном" in xml_parse.extract_http_exception_descr(body)


def test_decode_presentation_base64_nbsp() -> None:
    # platform often sends presentation as base64 UTF-8 with NBSP thousands
    raw = "NjPCoDkyN8KgNTA3wqAwNTLCoDU5Nw=="
    assert xml_parse.decode_presentation(raw) == "63 927 507 052 597"
    assert xml_parse.decode_presentation("NDI=") == "42"
    assert xml_parse.decode_presentation("ODQ=") == "84"
    assert xml_parse.decode_presentation("42") == "42"
    assert xml_parse.decode_presentation("Неопределено") == "Неопределено"


def test_parse_targets() -> None:
    targets = xml_parse.parse_targets(_load("targets.xml"))
    assert len(targets) >= 1
    assert targets[0].target_id == SPIKE_TARGET


def test_client_posts_cmd_and_headers() -> None:
    transport = MockTransport(
        {"attachDebugUI": HttpResponse(200, _load("attach_registered.xml"))}
    )
    client = DebugHttpClient("http://127.0.0.1:2550", transport=transport)
    resp = client.post("attachDebugUI", xml_build.build_attach("DefAlias", "x"))
    assert resp.status == 200
    assert xml_parse.extract_result(resp.body) == "registered"
    cmd, body, dbgui = transport.calls[0]
    assert cmd == "attachDebugUI"
    assert "DefAlias" in body
    assert dbgui is None


def test_ping_without_body_uses_dbgui() -> None:
    transport = MockTransport({"pingDebugUIParams": HttpResponse(200, "")})
    client = DebugHttpClient("http://localhost:2550", transport=transport)
    client.post("pingDebugUIParams", "", dbgui="session-xyz")
    cmd, body, dbgui = transport.calls[0]
    assert cmd == "pingDebugUIParams"
    assert body == ""
    assert dbgui == "session-xyz"


def test_attach_ib_in_debug_retry() -> None:
    transport = MockTransport(
        {
            "attachDebugUI": [
                HttpResponse(200, _load("attach_ib_in_debug.xml")),
                HttpResponse(200, _load("attach_registered.xml")),
            ],
            "detachDebugUI": HttpResponse(200, _load("detach_ok.xml")),
            "initSettings": HttpResponse(200, "<response><result>1</result></response>"),
            "setAutoAttachSettings": HttpResponse(
                200, "<response><result>1</result></response>"
            ),
        }
    )
    client = DebugHttpClient("http://localhost:2550", transport=transport)
    session = DebugSession(client, session_id="sid-retry", ping_interval=60.0)
    result = session.attach(start_ping=False)
    assert result.result == "registered"
    assert result.attempts == 2
    assert session.attached
    cmds = [c[0] for c in transport.calls]
    assert cmds.count("attachDebugUI") == 2
    assert "detachDebugUI" in cmds
    session.detach()


def test_force_detach_rotates_session_id() -> None:
    transport = MockTransport(
        {
            "attachDebugUI": HttpResponse(200, _load("attach_registered.xml")),
            "detachDebugUI": HttpResponse(200, _load("detach_ok.xml")),
            "initSettings": HttpResponse(200, "<response/>"),
            "setAutoAttachSettings": HttpResponse(200, "<response/>"),
        }
    )
    client = DebugHttpClient("http://localhost:2550", transport=transport)
    session = DebugSession(client, session_id="old-id", ping_interval=60.0)
    session.attach(start_ping=False)
    old = session.session_id
    session.force_detach()
    assert session.session_id != old
    assert not session.attached


def test_process_ping_target_and_stop() -> None:
    transport = MockTransport(
        {
            "attachDebugUI": HttpResponse(200, _load("attach_registered.xml")),
            "initSettings": HttpResponse(200, "<response/>"),
            "setAutoAttachSettings": HttpResponse(200, "<response/>"),
            "attachDetachDbgTargets": HttpResponse(200, "<response/>"),
            "setBreakpoints": HttpResponse(200, "<response/>"),
            "detachDebugUI": HttpResponse(200, _load("detach_ok.xml")),
        }
    )
    client = DebugHttpClient("http://localhost:2550", transport=transport)
    session = DebugSession(client, session_id="sid", ping_interval=60.0)
    session.attach(start_ping=False)
    session.set_breakpoints(
        [
            BreakpointSpec(
                object_id=SPIKE_OBJECT_ID,
                property_id=PROPERTY_ID_COMMON_MODULE,
                lines=(5,),
            )
        ]
    )
    events = session.process_ping_body(_load("ping_target_started.xml"))
    assert any(e.type == "targetStarted" for e in events)
    assert SPIKE_TARGET in session._attached_targets  # noqa: SLF001
    # BP re-sent after target attach
    assert any(c[0] == "setBreakpoints" for c in transport.calls)

    events2 = session.process_ping_body(_load("ping_call_stack.xml"))
    assert any(e.type == "callStackFormed" for e in events2)
    assert session.last_stop is not None
    assert session.last_stop.line_no == 5
    stack = session.stack()
    assert stack[-1].line_no == 5
    session.detach()


def test_wait_for_stop_timeout() -> None:
    transport = MockTransport(
        {
            "attachDebugUI": HttpResponse(200, _load("attach_registered.xml")),
            "initSettings": HttpResponse(200, "<response/>"),
            "setAutoAttachSettings": HttpResponse(200, "<response/>"),
            "getDbgAllTargetStates": HttpResponse(200, "<response/>"),
            "pingDebugUIParams": HttpResponse(200, ""),
            "detachDebugUI": HttpResponse(200, _load("detach_ok.xml")),
        }
    )
    client = DebugHttpClient("http://localhost:2550", transport=transport)
    session = DebugSession(client, session_id="sid", ping_interval=0.05)
    session.attach(start_ping=False)
    with pytest.raises(DebugHttpError) as exc:
        session.wait_for_stop(timeout=0.15)
    assert exc.value.code == CODE_WAIT_TIMEOUT
    session.detach()


def test_ensure_targets_attached_from_states() -> None:
    """CLI may miss targetStarted; wait/BP sync via getDbgAllTargetStates."""
    transport = MockTransport(
        {
            "attachDebugUI": HttpResponse(200, _load("attach_registered.xml")),
            "initSettings": HttpResponse(200, "<response/>"),
            "setAutoAttachSettings": HttpResponse(200, "<response/>"),
            "getDbgAllTargetStates": HttpResponse(200, _load("targets.xml")),
            "attachDetachDbgTargets": HttpResponse(200, "<response/>"),
            "setBreakpoints": HttpResponse(200, "<response/>"),
            "detachDebugUI": HttpResponse(200, _load("detach_ok.xml")),
        }
    )
    client = DebugHttpClient("http://localhost:2550", transport=transport)
    session = DebugSession(client, session_id="sid", ping_interval=60.0)
    session.attach(start_ping=False)
    session.set_breakpoints(
        [
            BreakpointSpec(
                object_id=SPIKE_OBJECT_ID,
                property_id=PROPERTY_ID_COMMON_MODULE,
                lines=(5,),
            )
        ]
    )
    found = session.ensure_targets_attached(force=True)
    assert found[0].target_id == SPIKE_TARGET
    assert SPIKE_TARGET in session._attached_targets  # noqa: SLF001
    assert any(c[0] == "attachDetachDbgTargets" for c in transport.calls)
    assert sum(1 for c in transport.calls if c[0] == "setBreakpoints") >= 2
    session.detach()


def test_variables_http_400_not_stopped_raises() -> None:
    body = (
        '<?xml version="1.0"?><exception reason="400">'
        "<descr>Выполнение вычислений возможно только в остановленном "
        "предмете отладки</descr></exception>"
    )
    transport = MockTransport(
        {
            "attachDebugUI": HttpResponse(200, _load("attach_registered.xml")),
            "initSettings": HttpResponse(200, "<response/>"),
            "setAutoAttachSettings": HttpResponse(200, "<response/>"),
            "evalLocalVariables": HttpResponse(400, body),
            "detachDebugUI": HttpResponse(200, _load("detach_ok.xml")),
        }
    )
    client = DebugHttpClient("http://localhost:2550", transport=transport)
    session = DebugSession(client, session_id="sid", ping_interval=60.0)
    session.attach(start_ping=False)
    session.process_ping_body(_load("ping_call_stack.xml"))
    with pytest.raises(DebugHttpError) as exc_info:
        session.variables()
    assert exc_info.value.code == CODE_NOT_STOPPED
    session.detach()


def test_variables_and_evaluate() -> None:
    transport = MockTransport(
        {
            "attachDebugUI": HttpResponse(200, _load("attach_registered.xml")),
            "initSettings": HttpResponse(200, "<response/>"),
            "setAutoAttachSettings": HttpResponse(200, "<response/>"),
            "evalLocalVariables": HttpResponse(200, _load("eval_locals.xml")),
            "evalExpr": HttpResponse(200, _load("eval_expr.xml")),
            "step": HttpResponse(200, "<response><result>1</result></response>"),
            "detachDebugUI": HttpResponse(200, _load("detach_ok.xml")),
        }
    )
    client = DebugHttpClient("http://localhost:2550", transport=transport)
    session = DebugSession(client, session_id="sid", ping_interval=60.0)
    session.attach(start_ping=False)
    session.process_ping_body(_load("ping_call_stack.xml"))

    locals_res = session.variables()
    assert locals_res.ok
    assert any(v.name == "Значение" for v in locals_res.variables)

    expr = session.evaluate("Конец")
    assert expr.state == "correctly"

    session.continue_()
    assert any(c[0] == "step" and "Continue" in c[1] for c in transport.calls)
    session.detach()


def test_step_in_out_pause() -> None:
    transport = MockTransport(
        {
            "attachDebugUI": HttpResponse(200, _load("attach_registered.xml")),
            "initSettings": HttpResponse(200, "<response/>"),
            "setAutoAttachSettings": HttpResponse(200, "<response/>"),
            "step": HttpResponse(200, "<response><result>1</result></response>"),
            "detachDebugUI": HttpResponse(200, _load("detach_ok.xml")),
        }
    )
    client = DebugHttpClient("http://localhost:2550", transport=transport)
    session = DebugSession(client, session_id="sid", ping_interval=60.0)
    session.attach(start_ping=False)
    session.process_ping_body(_load("ping_call_stack.xml"))
    session.step_in()
    session.step_over()
    session.step_out()
    session.pause()
    session.unpause()
    step_bodies = [c[1] for c in transport.calls if c[0] == "step"]
    assert any("StepIn" in b for b in step_bodies)
    assert any("<action>Step</action>" in b for b in step_bodies)
    assert any("StepOut" in b for b in step_bodies)
    init_bodies = [c[1] for c in transport.calls if c[0] == "initSettings"]
    assert any("true" in b for b in init_bodies)
    assert any("false" in b for b in init_bodies)
    session.detach()


def test_not_stopped_raises() -> None:
    transport = MockTransport(
        {
            "attachDebugUI": HttpResponse(200, _load("attach_registered.xml")),
            "initSettings": HttpResponse(200, "<response/>"),
            "setAutoAttachSettings": HttpResponse(200, "<response/>"),
            "detachDebugUI": HttpResponse(200, _load("detach_ok.xml")),
        }
    )
    client = DebugHttpClient("http://localhost:2550", transport=transport)
    session = DebugSession(client, session_id="sid", ping_interval=60.0)
    session.attach(start_ping=False)
    with pytest.raises(DebugHttpError) as exc:
        session.stack()
    assert exc.value.code == CODE_NOT_STOPPED
    session.detach()


def test_require_attached() -> None:
    client = DebugHttpClient(
        "http://localhost:2550",
        transport=MockTransport({}),
    )
    session = DebugSession(client, ping_interval=60.0)
    with pytest.raises(DebugHttpError) as exc:
        session.targets()
    assert exc.value.code == CODE_NO_SESSION


def test_stub_resolver_raises_1cd004() -> None:
    resolver = StubObjectIdResolver()
    with pytest.raises(DebugHttpError) as exc:
        resolver.resolve("ОтладкаДемо", "CommonModule")
    assert exc.value.code == CODE_MODULE_UNRESOLVED


def test_stub_resolver_override_and_set_by_module() -> None:
    ref = ModuleRef(
        object_id=SPIKE_OBJECT_ID,
        property_id=PROPERTY_ID_COMMON_MODULE,
        module_name="ОтладкаДемо",
        module_type="CommonModule",
    )
    resolver = StubObjectIdResolver(
        overrides={("ОтладкаДемо", "CommonModule", ""): ref}
    )
    transport = MockTransport(
        {
            "attachDebugUI": HttpResponse(200, _load("attach_registered.xml")),
            "initSettings": HttpResponse(200, "<response/>"),
            "setAutoAttachSettings": HttpResponse(200, "<response/>"),
            "setBreakpoints": HttpResponse(200, "<response/>"),
            "detachDebugUI": HttpResponse(200, _load("detach_ok.xml")),
        }
    )
    client = DebugHttpClient("http://localhost:2550", transport=transport)
    session = DebugSession(
        client, session_id="sid", resolver=resolver, ping_interval=60.0
    )
    session.attach(start_ping=False)
    spec = session.set_breakpoints_by_module("ОтладкаДемо", "CommonModule", [5])
    assert spec.object_id == SPIKE_OBJECT_ID
    assert any(SPIKE_OBJECT_ID in c[1] for c in transport.calls if c[0] == "setBreakpoints")
    session.clear_breakpoints()
    session.detach()


def test_xml_resolver_set_breakpoints_by_module() -> None:
    """Интеграция session + XmlObjectIdResolver на фикстуре modules/."""
    modules_root = FIXTURES / "modules" / "main"
    resolver = XmlObjectIdResolver(
        build_modules_index([SourceRoot(path=modules_root)])
    )
    transport = MockTransport(
        {
            "attachDebugUI": HttpResponse(200, _load("attach_registered.xml")),
            "initSettings": HttpResponse(200, "<response/>"),
            "setAutoAttachSettings": HttpResponse(200, "<response/>"),
            "setBreakpoints": HttpResponse(200, "<response/>"),
            "detachDebugUI": HttpResponse(200, _load("detach_ok.xml")),
        }
    )
    client = DebugHttpClient("http://localhost:2550", transport=transport)
    session = DebugSession(
        client, session_id="sid", resolver=resolver, ping_interval=60.0
    )
    session.attach(start_ping=False)
    spec = session.set_breakpoints_by_module("ОтладкаДемо", "CommonModule", [5])
    assert spec.object_id == SPIKE_OBJECT_ID
    assert spec.property_id == PROPERTY_ID_COMMON_MODULE
    session.detach()


def test_targets_list() -> None:
    transport = MockTransport(
        {
            "attachDebugUI": HttpResponse(200, _load("attach_registered.xml")),
            "initSettings": HttpResponse(200, "<response/>"),
            "setAutoAttachSettings": HttpResponse(200, "<response/>"),
            "getDbgAllTargetStates": HttpResponse(200, _load("targets.xml")),
            "detachDebugUI": HttpResponse(200, _load("detach_ok.xml")),
        }
    )
    client = DebugHttpClient("http://localhost:2550", transport=transport)
    session = DebugSession(client, session_id="sid", ping_interval=60.0)
    session.attach(start_ping=False)
    targets = session.targets()
    assert targets[0].target_id == SPIKE_TARGET
    session.detach()
