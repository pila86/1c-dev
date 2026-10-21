#!/usr/bin/env python3
"""Spike #135: ручной HTTP Debug Protocol (dbgs) — прототип, не продукт.

Поднимает dbgs, клиент 1С с /Debug -http, attach → BP → wait → vars/eval → detach.

Пример (из каталога собранного проекта с file IB):

    python3 run_http_debug.py --ib .1c-dev/runtime/main --port 2550

Порт 1550 на dev-машинах часто занят сервером/кластером 1С — выбирайте свободный.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PLATFORM_ROOT = Path("/opt/1cv8/x86_64")

NS_RDBG = "http://v8.1c.ru/8.3/debugger/debugRDBGRequestResponse"
NS_BD = "http://v8.1c.ru/8.3/debugger/debugBaseData"
NS_BP = "http://v8.1c.ru/8.3/debugger/debugBreakpoints"
NS_CALC = "http://v8.1c.ru/8.3/debugger/debugCalculations"
NS_AA = "http://v8.1c.ru/8.3/debugger/debugAutoAttach"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

# Fixture constants (tests/fixtures/debug_spike)
OBJECT_ID = "b7e2c4a1-8f3d-4a6e-9c1b-2d5e8f0a3b6c"  # CommonModule.ОтладкаДемо
PROPERTY_ID = "d5963243-262e-4398-b4d7-fb16d06484f6"  # CommonModule body
BP_LINE = 5  # «Значение = 42; // BP-LINE» — BP на исполняемой строке, не на голом комментарии
# ManagedApplicationModule: Configuration uuid + ApplicationModule property
CONFIG_OBJECT_ID = "d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f80"
APP_PROPERTY_ID = "d22e852a-cf8a-4f77-8ccb-3548e7792bea"
APP_BP_LINE = 9  # ОтладкаДемо.ВыполнитьДемо(); (комментарий BP-LINE-APP на строке 8)
ALIAS = "DefAlias"
AUTO_ATTACH = ["Client", "ManagedClient", "Server", "ServerEmulation"]

XML_HDR = '<?xml version="1.0" encoding="UTF-8"?>'


def find_platform_bin(name: str) -> Path:
    versions = sorted(p for p in PLATFORM_ROOT.iterdir() if (p / name).is_file())
    if not versions:
        sys.exit(f"{name} не найден в {PLATFORM_ROOT}")
    return versions[-1] / name


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host if host not in ("localhost", "") else "127.0.0.1", port))
            return True
        except OSError:
            return False


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def request_xml(alias: str, dbg_id: str, body: str = "") -> str:
    return (
        f'{XML_HDR}<request xmlns="{NS_RDBG}">'
        f"<infoBaseAlias>{esc(alias)}</infoBaseAlias>"
        f"<idOfDebuggerUI>{esc(dbg_id)}</idOfDebuggerUI>"
        f"{body}</request>"
    )


def build_attach(alias: str, dbg_id: str, password: str = "") -> str:
    cred = f"<credentials>{esc(password)}</credentials>" if password else ""
    body = f"<options><foregroundAbility>true</foregroundAbility></options>{cred}"
    return request_xml(alias, dbg_id, body)


def build_detach(alias: str, dbg_id: str) -> str:
    return request_xml(alias, dbg_id)


def build_init_settings(alias: str, dbg_id: str, break_on_next: bool = False) -> str:
    v = "true" if break_on_next else "false"
    return request_xml(alias, dbg_id, f"<data><breakOnNextLine>{v}</breakOnNextLine></data>")


def build_auto_attach(alias: str, dbg_id: str, types: list[str]) -> str:
    targets = "".join(f"<aa:targetType>{esc(t)}</aa:targetType>" for t in types)
    body = (
        f'<autoAttachSettings xsi:type="aa:DebugAutoAttachSettings" '
        f'xmlns:xsi="{NS_XSI}" xmlns:aa="{NS_AA}">'
        f"{targets}<aa:areaName></aa:areaName></autoAttachSettings>"
    )
    return request_xml(alias, dbg_id, body)


def _module_bp_xml(object_id: str, property_id: str, lines: list[int]) -> str:
    bp_lines = "".join(
        f'<bpInfo xmlns="{NS_BP}">'
        f"<line>{ln}</line>"
        f"<isActive>true</isActive>"
        f"<breakOnCondition>false</breakOnCondition><condition></condition>"
        f"<breakOnParentMethod>false</breakOnParentMethod><parentMethod></parentMethod>"
        f"<breakOnHitCount>false</breakOnHitCount>"
        f"<hitCountVariant>0</hitCountVariant><hitCount>1</hitCount>"
        f"<temp>false</temp></bpInfo>"
        for ln in lines
    )
    module_id = (
        f'<type xmlns="{NS_BD}">ConfigModule</type>'
        f'<URL xmlns="{NS_BD}"></URL>'
        f'<extensionName xmlns="{NS_BD}"></extensionName>'
        f'<objectID xmlns="{NS_BD}">{esc(object_id)}</objectID>'
        f'<propertyID xmlns="{NS_BD}">{esc(property_id)}</propertyID>'
        f'<extId xmlns="{NS_BD}">0</extId>'
    )
    return f'<moduleBPInfo xmlns="{NS_BP}"><id xmlns="{NS_BP}">{module_id}</id>{bp_lines}</moduleBPInfo>'


def build_set_breakpoints(
    alias: str,
    dbg_id: str,
    modules: list[tuple[str, str, list[int]]],
) -> str:
    """modules: list of (object_id, property_id, lines)."""
    modules_xml = "".join(_module_bp_xml(oid, pid, lines) for oid, pid, lines in modules)
    return (
        f'{XML_HDR}<request xmlns="{NS_RDBG}">'
        f"<infoBaseAlias>{esc(alias)}</infoBaseAlias>"
        f"<idOfDebuggerUI>{esc(dbg_id)}</idOfDebuggerUI>"
        f"<bpWorkspace>{modules_xml}</bpWorkspace></request>"
    )


def fixture_breakpoints(*, include_app: bool = True) -> list[tuple[str, str, list[int]]]:
    mods = [(OBJECT_ID, PROPERTY_ID, [BP_LINE])]
    if include_app:
        mods.append((CONFIG_OBJECT_ID, APP_PROPERTY_ID, [APP_BP_LINE]))
    return mods


def build_step(alias: str, dbg_id: str, target_id: str, action: str) -> str:
    return (
        f'{XML_HDR}<request xmlns="{NS_RDBG}" xmlns:bd="{NS_BD}" xmlns:xsi="{NS_XSI}">'
        f"<infoBaseAlias>{esc(alias)}</infoBaseAlias>"
        f"<idOfDebuggerUI>{esc(dbg_id)}</idOfDebuggerUI>"
        f'<targetID xsi:type="bd:DebugTargetIdLight"><bd:id>{esc(target_id)}</bd:id></targetID>'
        f"<action>{esc(action)}</action><simple>false</simple></request>"
    )


def build_attach_targets(alias: str, dbg_id: str, target_ids: list[str], attach: bool = True) -> str:
    ids = "".join(
        f'<id xsi:type="bd:DebugTargetIdLight"><bd:id>{esc(t)}</bd:id></id>' for t in target_ids
    )
    return (
        f'{XML_HDR}<request xmlns="{NS_RDBG}" xmlns:bd="{NS_BD}" xmlns:xsi="{NS_XSI}">'
        f"<infoBaseAlias>{esc(alias)}</infoBaseAlias>"
        f"<idOfDebuggerUI>{esc(dbg_id)}</idOfDebuggerUI>"
        f"<attach>{'true' if attach else 'false'}</attach>{ids}</request>"
    )


def build_eval_locals(alias: str, dbg_id: str, target_id: str, result_id: str) -> str:
    expr = (
        f'<expr xsi:type="calc:CalculationSourceDataStorage">'
        f"<calc:stackLevel>0</calc:stackLevel><calc:srcCalcInfo>"
        f"<calc:expressionResultID>{esc(result_id)}</calc:expressionResultID>"
        f"<calc:interfaces>context</calc:interfaces></calc:srcCalcInfo>"
        f"<calc:presOptions><calc:maxTextSize>307200</calc:maxTextSize>"
        f"<calc:stopOnFirstEOL>false</calc:stopOnFirstEOL></calc:presOptions></expr>"
    )
    return (
        f'{XML_HDR}<request xmlns="{NS_RDBG}" xmlns:bd="{NS_BD}" '
        f'xmlns:calc="{NS_CALC}" xmlns:xsi="{NS_XSI}">'
        f"<infoBaseAlias>{esc(alias)}</infoBaseAlias>"
        f"<idOfDebuggerUI>{esc(dbg_id)}</idOfDebuggerUI>"
        f"<calcWaitingTime>5000</calcWaitingTime>"
        f'<targetID xsi:type="bd:DebugTargetIdLight"><bd:id>{esc(target_id)}</bd:id></targetID>'
        f"{expr}</request>"
    )


def build_eval_expr(alias: str, dbg_id: str, target_id: str, expression: str, result_id: str) -> str:
    expr = (
        f'<expr xsi:type="calc:CalculationSourceDataStorage">'
        f"<calc:stackLevel>0</calc:stackLevel><calc:srcCalcInfo>"
        f"<calc:expressionResultID>{esc(result_id)}</calc:expressionResultID>"
        f"<calc:calcItem><calc:itemType>expression</calc:itemType>"
        f"<calc:expression>{esc(expression)}</calc:expression>"
        f"<calc:property></calc:property></calc:calcItem>"
        f"<calc:interfaces>context</calc:interfaces></calc:srcCalcInfo>"
        f"<calc:presOptions><calc:maxTextSize>307200</calc:maxTextSize>"
        f"<calc:stopOnFirstEOL>false</calc:stopOnFirstEOL></calc:presOptions></expr>"
    )
    return (
        f'{XML_HDR}<request xmlns="{NS_RDBG}" xmlns:bd="{NS_BD}" '
        f'xmlns:calc="{NS_CALC}" xmlns:xsi="{NS_XSI}">'
        f"<infoBaseAlias>{esc(alias)}</infoBaseAlias>"
        f"<idOfDebuggerUI>{esc(dbg_id)}</idOfDebuggerUI>"
        f"<calcWaitingTime>5000</calcWaitingTime>"
        f'<targetID xsi:type="bd:DebugTargetIdLight"><bd:id>{esc(target_id)}</bd:id></targetID>'
        f"{expr}</request>"
    )


class DebugHttp:
    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")

    def post(self, cmd: str, body: str = "", *, dbgui: str | None = None) -> tuple[int, str]:
        q = f"cmd={cmd}"
        if dbgui:
            q += f"&dbgui={dbgui}"
        url = f"{self.base}/e1crdbg/rdbg?{q}"
        req = Request(
            url,
            data=body.encode("utf-8") if body else b"",
            method="POST",
            headers={
                "Content-Type": "application/xml; charset=utf-8",
                "Accept": "application/xml",
                "User-Agent": "1CV8",
            },
        )
        try:
            with urlopen(req, timeout=30) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            data = e.read().decode("utf-8", errors="replace") if e.fp else ""
            return e.code, data

    def test(self) -> None:
        url = f"{self.base}/e1crdbg/rdbgTest?cmd=test"
        req = Request(
            url,
            data=b"",
            method="POST",
            headers={
                "Content-Type": "application/xml; charset=utf-8",
                "Accept": "application/xml",
                "User-Agent": "1CV8",
            },
        )
        with urlopen(req, timeout=10) as resp:
            if resp.status >= 500:
                raise RuntimeError(f"dbgs test HTTP {resp.status}")


def extract_result(xml_body: str) -> str:
    if not xml_body.strip():
        return ""
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError:
        return ""
    for tag in ("result", "{http://v8.1c.ru/8.3/debugger/debugRDBGRequestResponse}result"):
        el = root.find(f".//{tag}") if not tag.startswith("{") else root.find(f".//{tag}")
        if el is not None and el.text:
            return el.text.strip()
    # local-name search
    for el in root.iter():
        if el.tag.endswith("result") and el.text:
            return el.text.strip()
    return ""


def parse_ping_events(xml_body: str) -> list[dict[str, Any]]:
    if not xml_body.strip():
        return []
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError:
        return []
    events: list[dict[str, Any]] = []
    for el in root.iter():
        local = el.tag.rsplit("}", 1)[-1]
        if local in ("callStackFormed", "exprEvaluated", "targetStarted", "targetQuit"):
            events.append({"type": local, "xml": ET.tostring(el, encoding="unicode")[:800]})
        if local == "cmdID" and el.text:
            events.append({"type": el.text.strip(), "xml": ""})
    # Also scan for cmdID siblings pattern
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "cmdID" or not el.text:
            continue
        cmd = el.text.strip()
        parent = None  # ElementTree has no parent; re-scan item blocks via string
        events.append({"type": cmd, "raw_cmd": True})
    return events


def find_in_xml(xml_body: str, local_name: str) -> list[str]:
    if not xml_body.strip():
        return []
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError:
        return []
    out: list[str] = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == local_name and el.text:
            out.append(el.text.strip())
    return out


def start_dbgs(dbgs: Path, host: str, port: int, notify: Path, work: Path) -> subprocess.Popen[bytes]:
    if not port_free(host, port):
        sys.exit(
            f"порт {port} занят — выберите другой (--port). "
            f"1550/1540/1541 часто заняты сервером 1С."
        )
    notify.unlink(missing_ok=True)
    argv = [
        str(dbgs),
        f"--addr={host}",
        f"--port={port}",
        f"--notify={notify}",
    ]
    log = open(work / "dbgs.log", "wb")  # noqa: SIM115 — живёт с процессом spike
    proc = subprocess.Popen(
        argv,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    for _ in range(50):
        if notify.exists() and notify.stat().st_size > 0:
            break
        if proc.poll() is not None:
            sys.exit(f"dbgs завершился rc={proc.returncode}; см. {work / 'dbgs.log'}")
        time.sleep(0.1)
    else:
        sys.exit(f"dbgs не записал --notify за 5с: {notify}")
    # dbgs пишет notify в UTF-16 LE (BOM FF FE) — не UTF-8
    raw = notify.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        notify_text = raw.decode("utf-16").strip()
    else:
        notify_text = raw.decode("utf-8", errors="replace").strip()
    print(f"dbgs pid={proc.pid} notify={notify_text!r}")
    return proc


def start_client(
    onecv8: Path,
    ib: Path,
    debugger_url: str,
    *,
    http_debug: bool,
    work: Path,
) -> subprocess.Popen[bytes]:
    argv = [str(onecv8), "ENTERPRISE", f"/F{ib.resolve()}"]
    if http_debug:
        # канон HTTP: /Debug -http -attach /DebuggerURL"http://…"
        argv.extend(["/Debug", "-http", "-attach", f'/DebuggerURL"{debugger_url}"'])
    else:
        argv.append("/Debug")
    env = os.environ.copy()
    if not env.get("DISPLAY"):
        print("WARN: DISPLAY не задан — клиенту нужен X (или xvfb-run)", file=sys.stderr)
    log = open(work / "client.log", "wb")  # noqa: SIM115
    proc = subprocess.Popen(
        argv,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    print(f"client pid={proc.pid} argv={' '.join(argv)}")
    return proc


def killpg(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def attach_with_retry(http: DebugHttp, alias: str, dbg_id: str, password: str = "") -> str:
    """Attach; on ibInDebug detach+retry. Returns result string."""
    last = ""
    for attempt in range(5):
        code, body = http.post("attachDebugUI", build_attach(alias, dbg_id, password))
        last = extract_result(body) or f"http={code}"
        print(f"  attach attempt {attempt + 1}: result={last!r} http={code}")
        if last in ("", "ok", "success") or (code == 200 and last not in ("ibInDebug", "notRegistered")):
            # empty/ok often means success
            if last == "ibInDebug":
                http.post("detachDebugUI", build_detach(alias, dbg_id))
                time.sleep(1)
                continue
            if last in ("notRegistered", "credentialsRequired", "fullCredentialsRequired"):
                raise RuntimeError(f"attach failed: {last}")
            return last
        if last == "ibInDebug":
            http.post("detachDebugUI", build_detach(alias, dbg_id))
            time.sleep(1)
            continue
        if last in ("notRegistered", "credentialsRequired", "fullCredentialsRequired"):
            raise RuntimeError(f"attach failed: {last}")
        return last
    raise RuntimeError(f"ibInDebug after retries; last={last}")


def force_detach(http: DebugHttp, alias: str, dbg_id: str) -> None:
    """Локальный force_detach: detach + новый session id остаётся на вызывающем."""
    code, body = http.post("detachDebugUI", build_detach(alias, dbg_id))
    print(f"  force_detach: http={code} result={extract_result(body)!r}")


def run_happy_path(args: argparse.Namespace) -> int:
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    dbgs = find_platform_bin("dbgs")
    onecv8 = find_platform_bin("1cv8")
    ib = Path(args.ib).resolve()
    if not (ib / "1Cv8.1CD").exists():
        sys.exit(f"нет file IB: {ib / '1Cv8.1CD'} (сначала 1c-dev build)")

    host = args.host
    port = args.port
    notify = work / "dbgs.notify"
    debugger_url = f"http://{host}:{port}"

    print(f"platform dbgs={dbgs}")
    print(f"DISPLAY={os.environ.get('DISPLAY', '')!r}")
    print(f"debug URL={debugger_url} (порт выбран явно; 1550 часто занят)")

    dbgs_proc = start_dbgs(dbgs, host, port, notify, work)
    client_proc: subprocess.Popen[bytes] | None = None
    dbg_id = str(uuid.uuid4())
    http = DebugHttp(debugger_url)

    try:
        for _ in range(30):
            try:
                http.test()
                break
            except (URLError, RuntimeError, OSError):
                time.sleep(0.2)
        else:
            sys.exit("dbgs не отвечает на rdbgTest")

        print(f"session id={dbg_id}")
        if args.force_detach_first:
            # симулируем залипшую сессию: attach → «забыть» → force_detach → attach снова
            zombie = str(uuid.uuid4())
            print("scenario: zombie attach then force_detach")
            attach_with_retry(http, ALIAS, zombie)
            force_detach(http, ALIAS, zombie)
            dbg_id = str(uuid.uuid4())
            print(f"new session id={dbg_id}")

        attach_with_retry(http, ALIAS, dbg_id, args.password)
        http.post("initSettings", build_init_settings(ALIAS, dbg_id, False))
        code, body = http.post("setAutoAttachSettings", build_auto_attach(ALIAS, dbg_id, AUTO_ATTACH))
        print(f"  autoAttach http={code} result={extract_result(body)!r}")

        include_app = not args.common_module_only
        bps = fixture_breakpoints(include_app=include_app)
        code, body = http.post("setBreakpoints", build_set_breakpoints(ALIAS, dbg_id, bps))
        print(f"  setBreakpoints modules={len(bps)} include_app={include_app} http={code}")

        client_proc = start_client(
            onecv8, ib, debugger_url, http_debug=not args.tcp_only, work=work
        )

        # wait for target + stop
        stop: dict[str, Any] | None = None
        target_id = ""
        deadline = time.time() + args.timeout
        print(f"waiting for stop (timeout={args.timeout}s)…")
        while time.time() < deadline:
            code, body = http.post("pingDebugUIParams", "", dbgui=dbg_id)
            if code == 400:
                print("  ping HTTP 400 — dbgs перезапущен? recovery: detach+reattach")
                force_detach(http, ALIAS, dbg_id)
                dbg_id = str(uuid.uuid4())
                attach_with_retry(http, ALIAS, dbg_id, args.password)
                http.post("initSettings", build_init_settings(ALIAS, dbg_id, False))
                http.post("setAutoAttachSettings", build_auto_attach(ALIAS, dbg_id, AUTO_ATTACH))
                http.post(
                    "setBreakpoints",
                    build_set_breakpoints(ALIAS, dbg_id, fixture_breakpoints()),
                )
                continue
            if "targetStarted" in body or "TargetStarted" in body:
                ids = find_in_xml(body, "id")
                # id цели обычно UUID; берём первый похожий
                cand = [i for i in ids if len(i) >= 32] or ids
                if cand:
                    target_id = cand[0]
                    http.post(
                        "attachDetachDbgTargets",
                        build_attach_targets(ALIAS, dbg_id, [target_id], True),
                    )
                    # BP нужно переотправить после attach цели (как в 1c-debug-mcp)
                    http.post(
                        "setBreakpoints",
                        build_set_breakpoints(
                            ALIAS, dbg_id, fixture_breakpoints(include_app=not args.common_module_only)
                        ),
                    )
                    print(f"  targetStarted id={target_id}; BP re-sent")
                    if not args.no_pause:
                        http.post(
                            "initSettings",
                            build_init_settings(ALIAS, dbg_id, True),
                        )
                        print("  initSettings breakOnNextLine=true")
            if "callStackFormed" in body:
                lines = find_in_xml(body, "lineNo")
                object_ids = find_in_xml(body, "objectID")
                property_ids = find_in_xml(body, "propertyID")
                # стек: [0]=caller … [-1]=текущий кадр (где стоит BP)
                stop = {
                    "targetId": target_id,
                    "lineNo": lines[-1] if lines else None,
                    "objectID": object_ids[-1] if object_ids else None,
                    "propertyID": property_ids[-1] if property_ids else None,
                    "stackFrames": len(object_ids),
                    "ping_snippet": body[:500],
                }
                (work / "stop_ping.xml").write_text(body)
                print(f"  STOP {stop}")
                break
            if int(time.time()) % 3 == 0:
                _, tbody = http.post("getDbgAllTargetStates", request_xml(ALIAS, dbg_id))
                tids = find_in_xml(tbody, "id")
                if tids and not target_id:
                    target_id = tids[0]
                    http.post(
                        "attachDetachDbgTargets",
                        build_attach_targets(ALIAS, dbg_id, [target_id], True),
                    )
                    http.post(
                        "setBreakpoints",
                        build_set_breakpoints(ALIAS, dbg_id, fixture_breakpoints()),
                    )
                    print(f"  targets via getDbgAllTargetStates: {tids[:3]}; BP re-sent")
            time.sleep(0.5)
        else:
            print("TIMEOUT wait_for_stop", file=sys.stderr)
            _, tbody = http.post("getDbgAllTargetStates", request_xml(ALIAS, dbg_id))
            (work / "last_targets.xml").write_text(tbody)
            return 124

        assert stop is not None
        http.post("initSettings", build_init_settings(ALIAS, dbg_id, False))

        tid = stop["targetId"] or target_id

        def summarize_eval(label: str, xml_body: str) -> None:
            (work / f"{label}.xml").write_text(xml_body)
            state = find_in_xml(xml_body, "evalResultState")
            props = find_in_xml(xml_body, "propName")
            types = find_in_xml(xml_body, "typeName")
            print(f"  {label}: state={state} props={props} types={types}")

        result_id = str(uuid.uuid4())
        code, body = http.post("evalLocalVariables", build_eval_locals(ALIAS, dbg_id, tid, result_id))
        print(f"  evalLocalVariables http={code} (результат синхронно в POST body на 8.3.25)")
        summarize_eval("eval_locals", body)

        result_id2 = str(uuid.uuid4())
        expr = args.eval_expr
        code, body = http.post(
            "evalExpr", build_eval_expr(ALIAS, dbg_id, tid, expr, result_id2)
        )
        print(f"  evalExpr {expr!r} http={code}")
        summarize_eval("eval_expr", body)

        code, body = http.post("step", build_step(ALIAS, dbg_id, tid, "Continue"))
        print(f"  Continue http={code} result={extract_result(body)!r}")

        code, body = http.post("detachDebugUI", build_detach(ALIAS, dbg_id))
        print(f"  detach http={code} result={extract_result(body)!r}")
        print("OK happy path")
        return 0
    finally:
        killpg(client_proc)
        killpg(dbgs_proc)


def main() -> None:
    p = argparse.ArgumentParser(description="Spike #135 HTTP debug prototype")
    p.add_argument("--ib", required=True, help="путь к file IB (каталог с 1Cv8.1CD)")
    p.add_argument("--host", default="localhost")
    p.add_argument(
        "--port",
        type=int,
        default=2550,
        help="порт dbgs (default 2550; не 1550 — часто занят сервером 1С)",
    )
    p.add_argument("--work", default="/tmp/debug-spike-run", help="каталог логов/notify")
    p.add_argument("--timeout", type=int, default=60, help="wait_for_stop timeout, сек")
    p.add_argument("--password", default="", help="пароль dbgs, если задан")
    p.add_argument(
        "--tcp-only",
        action="store_true",
        help="клиент только с /Debug (без -http) — для сравнения",
    )
    p.add_argument(
        "--force-detach-first",
        action="store_true",
        help="сценарий ibInDebug: zombie attach → force_detach → attach",
    )
    p.add_argument(
        "--no-pause",
        action="store_true",
        help="не выставлять breakOnNextLine (только module BP)",
    )
    p.add_argument(
        "--eval-expr",
        default="Конец",
        help="BSL-выражение для evalExpr (default: Конец из ManagedApplicationModule)",
    )
    p.add_argument(
        "--common-module-only",
        action="store_true",
        help="только BP в CommonModule.ОтладкаДемо (без ApplicationModule)",
    )
    args = p.parse_args()
    try:
        raise SystemExit(run_happy_path(args))
    except URLError as e:
        print(f"URL error: {e}", file=sys.stderr)
        raise SystemExit(4) from e


if __name__ == "__main__":
    main()
