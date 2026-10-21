"""M6 acceptance: отладка клиентских и серверных модулей на live-платформе (ADR-031).

Fixture ``debug_spike``: ``ПриНачалеРаботыСистемы`` (клиент) → ``ОтладкаДемо`` (клиентский
общий модуль) → ``ОтладкаСервер`` (серверный общий модуль, ``ServerCall``) →
``Справочники.Товары`` (модуль менеджера, затем модуль объекта ``ПередЗаписью``).

Сценарий: runtime start --debug --bp … → wait → variables/eval → continue → … → runtime stop.
Без ``ibcmd`` / ``1cv8`` / ``dbgs`` / DISPLAY — skip.

Расширение ``DebugExt`` (``src/cfe/debug_ext``): перехватчик ``&После`` в адоптированном
``ОтладкаДемо`` (клиент) и собственный серверный модуль ``Расш_ОтладкаСервер``;
второй тест проходит сценарий целиком через CLI (``typer.testing.CliRunner``);
третий — пошаговое выполнение (step-over / step-in / step-out) через CLI;
четвёртый — тот же happy-path через MCP ``debug.*`` / ``runtime.*`` (#144).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from adapters.platform import discover_environment
from adapters.platform_ibcmd.constants import IB_MARKER
from cli.main import app
from core.build import run_build
from core.debug import (
    DebugResult,
    run_continue,
    run_evaluate,
    run_step_over,
    run_variables,
    run_wait,
)
from core.runtime import run_start, run_stop
from mcp_server import create_server

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "debug_spike"

APP_BP = "src/main/Ext/ManagedApplicationModule.bsl:4"
MANAGER_BP = "src/main/Catalogs/Товары/Ext/ManagerModule.bsl:3"
OBJECT_BP = "src/main/Catalogs/Товары/Ext/ObjectModule.bsl:4"
SERVER_BP = "src/main/CommonModules/ОтладкаСервер/Ext/Module.bsl:10"
EXT_CLIENT_BP = "src/cfe/debug_ext/CommonModules/ОтладкаДемо/Ext/Module.bsl:5"
EXT_SERVER_BP = "src/cfe/debug_ext/CommonModules/Расш_ОтладкаСервер/Ext/Module.bsl:7"
EXTENSION = "DebugExt"

runner = CliRunner()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _variables(result: DebugResult) -> dict[str, str]:
    return {
        str(v.get("name")): str(v.get("presentation") or v.get("value") or "")
        for v in result.variables
    }


def _leaf(result: DebugResult) -> dict[str, object]:
    assert result.call_stack, result.to_payload()
    return result.call_stack[-1]


def _require_platform() -> None:
    discovery = discover_environment()
    if not discovery.ibcmd.found:
        pytest.skip("ibcmd не найден — M6 acceptance пропущен")
    if not discovery.onecv8.found:
        pytest.skip("1cv8 не найден — M6 acceptance пропущен")
    if not discovery.dbgs.found:
        pytest.skip("dbgs не найден — M6 acceptance пропущен")
    if sys.platform != "win32" and not os.environ.get("DISPLAY"):
        pytest.skip("нет DISPLAY для толстого клиента — M6 acceptance пропущен")


def _prepare_project(tmp_path: Path) -> Path:
    """Копия фикстуры + ``debug.port`` в манифесте + build (конфигурация и расширение)."""
    _require_platform()
    project = tmp_path / "debug_spike"
    shutil.copytree(
        FIXTURE, project, ignore=shutil.ignore_patterns("__pycache__", "run_http_debug.py")
    )
    manifest = project / ".1c-dev" / "project.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "\ndebug:\n  host: localhost\n"
        f"  port: {_free_port()}\n"
        "  infobaseAlias: DefAlias\n"
        "  autoAttachTypes: [Client, ManagedClient, Server, ServerEmulation]\n",
        encoding="utf-8",
    )

    build = run_build(project)
    assert build.status == "ok", build.to_payload()
    assert (project / ".1c-dev" / "runtime" / "main" / IB_MARKER).is_file()
    return project


def _cli(*args: str, expect_ok: bool = True) -> dict[str, Any]:
    """Вызов ``1c-dev … --output json`` из cwd проекта; JSON из stdout."""
    result = runner.invoke(app, [*args, "--output", "json"])
    payload = json.loads(result.stdout)
    if expect_ok:
        assert result.exit_code == 0, (args, result.exit_code, payload)
        assert payload.get("status") == "ok", (args, payload)
    return payload  # type: ignore[no-any-return]


def _cli_variables(payload: dict[str, Any]) -> dict[str, str]:
    return {
        str(v.get("name")): str(v.get("presentation") or v.get("value") or "")
        for v in payload.get("variables", [])
    }


def _cli_leaf(payload: dict[str, Any]) -> dict[str, Any]:
    stack = payload.get("callStack") or []
    assert stack, payload
    return stack[-1]  # type: ignore[no-any-return]


def _mcp(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Вызов MCP tool через FastMCP ``call_tool`` (как в ``test_mcp.py``)."""
    server = create_server()

    async def _run() -> dict[str, Any]:
        result = await server.call_tool(name, arguments or {})
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
            return result[1]
        raise AssertionError(f"Unexpected call_tool result: {result!r}")

    return asyncio.run(_run())


def _mcp_ok(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _mcp(name, arguments)
    assert payload.get("status") == "ok", (name, payload)
    return payload


@pytest.mark.integration
def test_m6_acceptance_client_and_server_modules(tmp_path: Path) -> None:
    project = _prepare_project(tmp_path)

    debug_dir = project / ".1c-dev" / "debug"
    try:
        started = run_start(
            project,
            debug=True,
            breakpoints=[APP_BP, MANAGER_BP, OBJECT_BP, SERVER_BP],
        )
        assert started.status == "ok", started.to_payload()
        assert started.targets_armed, started.to_payload()
        assert len(started.breakpoints) == 4

        # 1. клиентский модуль (ManagedApplicationModule)
        waited = run_wait(project, timeout=60)
        assert waited.status == "ok", waited.to_payload()
        assert (waited.module_name, waited.line_no) == ("DebugSpike", 4)
        assert _leaf(waited).get("moduleType") == "ManagedApplicationModule"
        variables = run_variables(project)
        assert "DebugSpike" in _variables(variables)["ИмяСценария"]
        evaluated = run_evaluate(project, expression="ИмяСценария")
        assert "DebugSpike" in (evaluated.result or "")

        # step-over: следующая строка клиентского модуля (вход в ОтладкаДемо без BP не нужен)
        stepped = run_step_over(project, timeout=30)
        assert stepped.status == "ok", stepped.to_payload()
        assert (stepped.module_name, stepped.line_no) == ("DebugSpike", 5)

        # 2. серверный: модуль менеджера справочника
        manager = run_continue(project, timeout=60)
        assert manager.status == "ok", manager.to_payload()
        assert (manager.module_name, manager.line_no) == ("Товары", 3)
        assert _leaf(manager).get("moduleType") == "ManagerModule"
        assert _variables(run_variables(project))["Префикс"] == '"Товар"'
        # клиентский кадр остаётся в стеке серверного вызова
        assert [f.get("moduleType") for f in manager.call_stack][0] == "ManagedApplicationModule"

        # 3. серверный: модуль объекта справочника (ПередЗаписью)
        obj = run_continue(project, timeout=60)
        assert obj.status == "ok", obj.to_payload()
        assert (obj.module_name, obj.line_no) == ("Товары", 4)
        assert _leaf(obj).get("moduleType") == "ObjectModule"
        assert "Отказ" in _variables(run_variables(project))

        # 4. серверный общий модуль
        server = run_continue(project, timeout=60)
        assert server.status == "ok", server.to_payload()
        assert (server.module_name, server.line_no) == ("ОтладкаСервер", 10)
        assert _leaf(server).get("moduleType") == "CommonModule"
        server_vars = _variables(run_variables(project))
        assert server_vars["СерверноеЗначение"] == "21"
        assert server_vars["СерверныйРезультат"] == "42"
        assert "Товар-DebugSpike" in server_vars["Элемент"]
        doubled = run_evaluate(project, expression="СерверныйРезультат * 2")
        assert doubled.result == "84"

        # финал: программа выполнена, клиент завершился
        done = run_continue(project, timeout=60)
        assert done.status == "ok", done.to_payload()
        assert not done.call_stack
    finally:
        stopped = run_stop(project)
        assert stopped.status == "ok", stopped.to_payload()

    assert not (debug_dir / "session.json").exists()
    assert not (debug_dir / "ping.pid").exists()
    assert not (debug_dir / "server.pid").exists()


@pytest.mark.integration
def test_m6_acceptance_extension_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Точки останова в расширении через CLI: runtime start --bp → wait → continue → stop."""
    project = _prepare_project(tmp_path)
    monkeypatch.chdir(project)
    debug_dir = project / ".1c-dev" / "debug"
    try:
        started = _cli(
            "runtime", "start", "--debug", "--bp", EXT_CLIENT_BP, "--bp", EXT_SERVER_BP
        )
        debug = started["debug"]
        assert debug["targetsArmed"], started
        # Оба BP — в расширении (не в одноимённом модуле основной конфигурации).
        assert {bp["extensionName"] for bp in debug["breakpoints"]} == {EXTENSION}
        assert {bp["moduleName"] for bp in debug["breakpoints"]} == {
            "ОтладкаДемо",
            "Расш_ОтладкаСервер",
        }

        # 1. адоптированный клиентский модуль: перехватчик &После("ВыполнитьДемо")
        waited = _cli("debug", "wait", "--timeout", "60")
        assert (waited["moduleName"], waited["lineNo"]) == ("ОтладкаДемо", 5)
        leaf = _cli_leaf(waited)
        assert leaf["extensionName"] == EXTENSION
        assert waited["callStack"][0]["moduleName"] == "DebugSpike"
        assert "extensionName" not in waited["callStack"][0]
        variables = _cli_variables(_cli("debug", "variables"))
        assert "DebugSpike" in variables["ИмяСценария"]
        assert variables["РасширениеСценарий"] == '"DebugSpike+ext"'

        # 2. собственный серверный модуль расширения (ServerCall)
        server = _cli("debug", "continue", "--timeout", "60")
        assert (server["moduleName"], server["lineNo"]) == ("Расш_ОтладкаСервер", 7)
        assert _cli_leaf(server)["extensionName"] == EXTENSION
        server_vars = _cli_variables(_cli("debug", "variables"))
        assert server_vars["РасширениеЗначение"] == "7"
        assert server_vars["РасширениеРезультат"] == "42"
        evaluated = _cli("debug", "eval", "РасширениеРезультат * 2")
        assert evaluated["result"] == "84"
        # клиентский кадр расширения остаётся в стеке серверного вызова
        names = [f["moduleName"] for f in server["callStack"]]
        assert names == ["DebugSpike", "ОтладкаДемо", "Расш_ОтладкаСервер"]

        # финал: программа выполнена, клиент завершился
        done = _cli("debug", "continue", "--timeout", "60")
        assert not done.get("callStack")
    finally:
        stopped = _cli("runtime", "stop", expect_ok=False)
        assert stopped["status"] == "ok", stopped

    assert not (debug_dir / "session.json").exists()
    assert not (debug_dir / "ping.pid").exists()
    assert not (debug_dir / "server.pid").exists()


def _assert_at(payload: dict[str, Any], module: str, line: int, depth: int) -> None:
    leaf = _cli_leaf(payload)
    assert (payload["moduleName"], payload["lineNo"]) == (module, line), payload
    assert leaf["moduleName"] == module, payload
    assert len(payload["callStack"]) == depth, payload


@pytest.mark.integration
def test_m6_acceptance_steps_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """step-over / step-in / step-out через CLI от BP в ManagedApplicationModule."""
    project = _prepare_project(tmp_path)
    monkeypatch.chdir(project)
    debug_dir = project / ".1c-dev" / "debug"
    try:
        _cli("runtime", "start", "--debug", "--bp", APP_BP)
        waited = _cli("debug", "wait", "--timeout", "60")
        _assert_at(waited, "DebugSpike", 4, 1)

        # step-over: следующая строка клиентского модуля
        over = _cli("debug", "step-over", "--timeout", "30")
        _assert_at(over, "DebugSpike", 5, 1)
        # шаги не помечены как экспериментальные
        assert not [d for d in over.get("diagnostics", []) if d.get("severity") == "warning"]

        # step-in: заход в серверный общий модуль, клиентский кадр остаётся в стеке
        into = _cli("debug", "step-in", "--timeout", "30")
        _assert_at(into, "ОтладкаСервер", 5, 2)
        assert [f["moduleName"] for f in into["callStack"]] == ["DebugSpike", "ОтладкаСервер"]

        # step-over внутри сервера, по строкам
        _assert_at(_cli("debug", "step-over", "--timeout", "30"), "ОтладкаСервер", 6, 2)
        seven = _cli("debug", "step-over", "--timeout", "30")
        _assert_at(seven, "ОтладкаСервер", 7, 2)
        server_vars = _cli_variables(_cli("debug", "variables"))
        assert server_vars["СерверноеЗначение"] == "21"
        assert server_vars["СерверныйРезультат"] == "42"

        # step-out: возврат на строку вызова в клиентском модуле
        out = _cli("debug", "step-out", "--timeout", "30")
        _assert_at(out, "DebugSpike", 5, 1)

        # продолжаем шагами до конца процедуры
        _assert_at(_cli("debug", "step-over", "--timeout", "30"), "DebugSpike", 6, 1)
        _assert_at(_cli("debug", "step-over", "--timeout", "30"), "DebugSpike", 8, 1)
        final = _cli("debug", "variables")
        assert _cli_variables(final)["СерверныйИтог"] == "42"

        # финал: программа выполнена, клиент завершился (ok + warning, не ошибка)
        done = _cli("debug", "continue", "--timeout", "60")
        assert not done.get("callStack")
    finally:
        stopped = _cli("runtime", "stop", expect_ok=False)
        assert stopped["status"] == "ok", stopped

    assert not (debug_dir / "session.json").exists()
    assert not (debug_dir / "ping.pid").exists()
    assert not (debug_dir / "server.pid").exists()


@pytest.mark.integration
def test_m6_acceptance_mcp(tmp_path: Path) -> None:
    """Happy-path через MCP: server → attach → BP → runtime → wait → vars/eval → stop."""
    project = _prepare_project(tmp_path)
    path = str(project)
    app_file, _, app_line = APP_BP.rpartition(":")
    debug_dir = project / ".1c-dev" / "debug"
    try:
        _mcp_ok("debug.server.start", {"path": path})
        _mcp_ok("debug.attach", {"path": path})
        bp = _mcp_ok(
            "debug.breakpoint",
            {"path": path, "file": app_file, "lines": [int(app_line)]},
        )
        assert bp.get("breakpoints"), bp

        started = _mcp_ok("runtime.start", {"path": path, "debug": True})
        debug = started.get("debug") or {}
        assert debug.get("targetsArmed"), started

        waited = _mcp_ok("debug.wait", {"path": path, "timeout": 60})
        assert (waited.get("moduleName"), waited.get("lineNo")) == ("DebugSpike", 4)
        variables = _cli_variables(_mcp_ok("debug.variables", {"path": path}))
        assert "DebugSpike" in variables["ИмяСценария"]
        evaluated = _mcp_ok(
            "debug.evaluate", {"path": path, "expression": "ИмяСценария"}
        )
        assert "DebugSpike" in str(evaluated.get("result") or "")

        done = _mcp_ok("debug.continue", {"path": path, "timeout": 60})
        assert not done.get("callStack")
    finally:
        stopped = _mcp("runtime.stop", {"path": path})
        assert stopped.get("status") == "ok", stopped

    assert not (debug_dir / "session.json").exists()
    assert not (debug_dir / "ping.pid").exists()
    assert not (debug_dir / "server.pid").exists()


# --- #147: test.run --debug --bp → debug.wait → test.wait ---

YAXUNIT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "yaxunit_spike"
TEST_ARITH_BP = "src/cfe/test_ext1/CommonModules/ОМ_Арифметика/Ext/Module.bsl:18"


def _ensure_yaxunit_cfe() -> Path:
    import urllib.error

    from core.toolchain.cache import tools_cache_dir
    from core.toolchain.fetchers.yaxunit import fetch_yaxunit
    from core.toolchain.manifest import load_manifest
    from core.toolchain.resolve import resolve_yaxunit_cfe

    resolved = resolve_yaxunit_cfe()
    if resolved.found and resolved.path is not None:
        return resolved.path

    env_name = resolved.env_name or "ONEC_YAXUNIT_CFE"
    skip_msg = (
        f"YAxUnit.cfe не найден — выполните 1c-dev tools sync "
        f"или задайте {env_name}=/path/to/YAxUnit.cfe"
    )
    manifest = load_manifest()
    spec = manifest.get("yaxunit")
    if spec is None:
        pytest.skip(skip_msg)

    try:
        path, _diags = fetch_yaxunit(spec, tools_cache_dir(), quiet=True)
    except (OSError, urllib.error.URLError) as exc:
        pytest.skip(f"{skip_msg} ({exc})")

    if path is None or not path.is_file():
        resolved = resolve_yaxunit_cfe()
        if resolved.found and resolved.path is not None:
            return resolved.path
        pytest.skip(skip_msg)
    return path


def _prepare_yaxunit_debug_project(tmp_path: Path) -> Path:
    """yaxunit_spike + debug.port + build (для test.run --debug)."""
    _require_platform()
    yaxunit_cfe = _ensure_yaxunit_cfe()
    assert yaxunit_cfe.is_file()

    project = tmp_path / "yaxunit_spike"
    shutil.copytree(
        YAXUNIT_FIXTURE, project, ignore=shutil.ignore_patterns("run_yaxunit.py")
    )
    manifest = project / ".1c-dev" / "project.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "\ndebug:\n  host: localhost\n"
        f"  port: {_free_port()}\n"
        "  infobaseAlias: DefAlias\n"
        "  autoAttachTypes: [Client, ManagedClient, Server, ServerEmulation]\n",
        encoding="utf-8",
    )
    build = run_build(project)
    assert build.status == "ok", build.to_payload()
    assert (project / ".1c-dev" / "runtime" / "main" / IB_MARKER).is_file()
    return project


@pytest.mark.integration
def test_m6_acceptance_test_run_debug(tmp_path: Path) -> None:
    """#147: test runOne --debug --bp → wait → continue → test wait → passed."""
    from core.debug import teardown_debug
    from core.test import run_one_test, wait_tests

    project = _prepare_yaxunit_debug_project(tmp_path)
    debug_dir = project / ".1c-dev" / "debug"
    try:
        started = run_one_test(
            "ОМ_Арифметика.Сложение",
            project,
            debug=True,
            breakpoints=[TEST_ARITH_BP],
        )
        assert started.status == "running", started.to_payload()
        assert started.pid is not None
        assert started.debug_enabled is True

        waited = run_wait(project, timeout=90)
        assert waited.status == "ok", waited.to_payload()
        assert waited.module_name == "ОМ_Арифметика"
        assert waited.line_no == 18

        done = run_continue(project, timeout=90)
        assert done.status == "ok", done.to_payload()

        finished = wait_tests(project, timeout=120)
        assert finished.status == "passed", finished.to_payload()
        assert finished.exit_code == 0
        assert (finished.passed or 0) >= 1
        # test.wait tears down debug like runtime.stop
        assert not (debug_dir / "session.json").exists()
        assert not (debug_dir / "ping.pid").exists()
    finally:
        # Best-effort if wait failed before teardown
        teardown_debug(project)
        meta = project / ".1c-dev" / "test" / "run.meta.json"
        if meta.is_file():
            wait_tests(project, timeout=30)
