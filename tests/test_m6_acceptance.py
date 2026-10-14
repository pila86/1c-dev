"""M6 acceptance: отладка клиентских и серверных модулей на live-платформе (ADR-031).

Fixture ``debug_spike``: ``ПриНачалеРаботыСистемы`` (клиент) → ``ОтладкаДемо`` (клиентский
общий модуль) → ``ОтладкаСервер`` (серверный общий модуль, ``ServerCall``) →
``Справочники.Товары`` (модуль менеджера, затем модуль объекта ``ПередЗаписью``).

Сценарий: runtime start --debug --bp … → wait → variables/eval → continue → … → runtime stop.
Без ``ibcmd`` / ``1cv8`` / ``dbgs`` / DISPLAY — skip.

Расширение ``DebugExt`` (``src/cfe/debug_ext``): перехватчик ``&После`` в адоптированном
``ОтладкаДемо`` (клиент) и собственный серверный модуль ``Расш_ОтладкаСервер``;
второй тест проходит сценарий целиком через CLI (``typer.testing.CliRunner``).
"""

from __future__ import annotations

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
