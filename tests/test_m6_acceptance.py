"""M6 acceptance: отладка клиентских и серверных модулей на live-платформе (ADR-031).

Fixture ``debug_spike``: ``ПриНачалеРаботыСистемы`` (клиент) → ``ОтладкаДемо`` (клиентский
общий модуль) → ``ОтладкаСервер`` (серверный общий модуль, ``ServerCall``) →
``Справочники.Товары`` (модуль менеджера, затем модуль объекта ``ПередЗаписью``).

Сценарий: runtime start --debug --bp … → wait → variables/eval → continue → … → runtime stop.
Без ``ibcmd`` / ``1cv8`` / ``dbgs`` / DISPLAY — skip.
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
from pathlib import Path

import pytest

from adapters.platform import discover_environment
from adapters.platform_ibcmd.constants import IB_MARKER
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

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "debug_spike"

APP_BP = "src/main/Ext/ManagedApplicationModule.bsl:4"
MANAGER_BP = "src/main/Catalogs/Товары/Ext/ManagerModule.bsl:3"
OBJECT_BP = "src/main/Catalogs/Товары/Ext/ObjectModule.bsl:4"
SERVER_BP = "src/main/CommonModules/ОтладкаСервер/Ext/Module.bsl:10"


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


@pytest.mark.integration
def test_m6_acceptance_client_and_server_modules(tmp_path: Path) -> None:
    discovery = discover_environment()
    if not discovery.ibcmd.found:
        pytest.skip("ibcmd не найден — M6 acceptance пропущен")
    if not discovery.onecv8.found:
        pytest.skip("1cv8 не найден — M6 acceptance пропущен")
    if not discovery.dbgs.found:
        pytest.skip("dbgs не найден — M6 acceptance пропущен")
    if sys.platform != "win32" and not os.environ.get("DISPLAY"):
        pytest.skip("нет DISPLAY для толстого клиента — M6 acceptance пропущен")

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
