"""CLI: 1c-dev debug … (ADR-031 / #140)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from cli.options import ConfigOption, RuntimeOption
from cli.output import OutputFormat, OutputOption, resolve_output
from core.debug import (
    DEFAULT_WAIT_TIMEOUT_SEC,
    DebugResult,
    run_attach,
    run_breakpoint_clear,
    run_breakpoint_set,
    run_continue,
    run_detach,
    run_evaluate,
    run_force_detach,
    run_pause,
    run_ping_start,
    run_ping_status,
    run_ping_stop,
    run_reload_metadata,
    run_server_start,
    run_server_status,
    run_server_stop,
    run_stack,
    run_status,
    run_step_in,
    run_step_out,
    run_step_over,
    run_targets,
    run_variables,
    run_wait,
)

app = typer.Typer(
    name="debug",
    help=(
        "Debug API: HTTP dbgs. Сценарий: runtime start --debug --bp … → "
        "debug wait → variables/eval → continue → runtime stop. "
        "step-in/over/out и pause — экспериментальные (могут не работать)."
    ),
    add_completion=False,
    no_args_is_help=True,
)

server_app = typer.Typer(
    name="server",
    help="Lifecycle HTTP Debug Server (dbgs).",
    add_completion=False,
    no_args_is_help=True,
)
app.add_typer(server_app, name="server")

breakpoint_app = typer.Typer(
    name="breakpoint",
    help="Точки останова.",
    add_completion=False,
    no_args_is_help=True,
)
app.add_typer(breakpoint_app, name="breakpoint")

ping_app = typer.Typer(
    name="ping",
    help="Ping-демон (единственный читатель pingDebugUIParams; диагностика).",
    add_completion=False,
    no_args_is_help=True,
)
app.add_typer(ping_app, name="ping")


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _diag_lines(result: DebugResult) -> list[str]:
    lines: list[str] = []
    for diag in result.diagnostics:
        code = diag.get("code", "")
        severity = diag.get("severity", "error")
        prefix = f"[{code}] " if code else ""
        label = "warning" if severity == "warning" else "error"
        lines.append(f"{label}: {prefix}{diag.get('message', '')}")
        suggestion = diag.get("suggestion")
        if suggestion:
            lines.append(f"  → {suggestion}")
    return lines


def _result_text(result: DebugResult) -> list[str]:
    lines = [f"status: {result.status}"]
    if result.config_id:
        lines.append(f"config: {result.config_id}")
    if result.runtime_id:
        lines.append(f"runtime: {result.runtime_id}")
    if result.duration is not None:
        lines.append(f"duration: {result.duration:.3f}s")
    if result.running is not None:
        lines.append(f"running: {str(result.running).lower()}")
    if result.pid is not None:
        lines.append(f"pid: {result.pid}")
    if result.host is not None:
        lines.append(f"host: {result.host}")
    if result.port is not None:
        lines.append(f"port: {result.port}")
    if result.url is not None:
        lines.append(f"url: {result.url}")
    if result.attached is not None:
        lines.append(f"attached: {str(result.attached).lower()}")
    if result.session_id:
        lines.append(f"sessionId: {result.session_id}")
    if result.alias:
        lines.append(f"alias: {result.alias}")
    if result.target_id:
        lines.append(f"targetId: {result.target_id}")
    if result.module_name:
        lines.append(f"module: {result.module_name}")
    if result.line_no is not None:
        lines.append(f"line: {result.line_no}")
    if result.expression:
        lines.append(f"expression: {result.expression}")
    if result.result is not None:
        lines.append(f"result: {result.result}")
    if result.eval_state is not None:
        lines.append(f"evalState: {result.eval_state}")
    if result.modules_count is not None:
        lines.append(f"modules: {result.modules_count}")
    if result.client_debug_enabled is not None:
        lines.append(f"clientDebug: {str(result.client_debug_enabled).lower()}")
    if result.debugger_url:
        lines.append(f"debuggerUrl: {result.debugger_url}")
    if result.ping_running is not None:
        lines.append(f"pingRunning: {str(result.ping_running).lower()}")
    if result.ping_pid is not None:
        lines.append(f"pingPid: {result.ping_pid}")
    if result.targets:
        lines.append(f"targets: {len(result.targets)}")
        for t in result.targets[:20]:
            lines.append(
                f"  - {t.get('targetId', '')} [{t.get('targetType', '')} {t.get('state', '')}]"
            )
    if result.call_stack:
        lines.append(f"callStack: {len(result.call_stack)}")
        for frame in result.call_stack[:20]:
            name = frame.get("moduleName") or frame.get("objectId", "")
            mtype = frame.get("moduleType") or ""
            suffix = f" [{mtype}]" if mtype else ""
            lines.append(f"  - {name}:{frame.get('lineNo', '')}{suffix}")
    if result.variables:
        lines.append(f"variables: {len(result.variables)}")
        for var in result.variables[:20]:
            shown = var.get("presentation") or var.get("value", "")
            typ = var.get("type") or ""
            type_s = f" ({typ})" if typ else ""
            name = var.get("name") or "<result>"
            lines.append(f"  - {name}={shown}{type_s}")
    if result.breakpoints:
        lines.append(f"breakpoints: {len(result.breakpoints)}")
        for bp in result.breakpoints:
            lines.append(
                f"  - {bp.get('moduleName', bp.get('objectId', ''))} "
                f"lines={bp.get('lines', [])}"
            )
    lines.extend(_diag_lines(result))
    return lines


def finish(result: DebugResult, ctx: typer.Context, output: OutputOption) -> None:
    """Emit result (json/text) and exit with ``result.exit_code``."""
    _emit(
        result.to_payload(),
        resolve_output(ctx, output),
        text_lines=_result_text(result),
    )
    raise typer.Exit(code=result.exit_code)


@server_app.command("start")
def server_start_cmd(
    ctx: typer.Context,
    host: str | None = typer.Option(
        None,
        "--host",
        help="Host dbgs (default: manifest/localhost).",
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        help="Порт dbgs (обязателен, если нет debug.port в манифесте).",
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Поднять HTTP Debug Server (dbgs)."""
    finish(
        run_server_start(Path.cwd(), host=host, port=port, config_id=config, runtime_id=runtime),
        ctx,
        output,
    )


@server_app.command("stop")
def server_stop_cmd(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Остановить dbgs, если стартовали мы."""
    finish(
        run_server_stop(Path.cwd(), config_id=config, runtime_id=runtime),
        ctx,
        output,
    )


@server_app.command("status")
def server_status_cmd(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Статус dbgs (pid / url / liveness)."""
    finish(
        run_server_status(Path.cwd(), config_id=config, runtime_id=runtime),
        ctx,
        output,
    )


@app.command("attach")
def attach_cmd(
    ctx: typer.Context,
    url: str | None = typer.Option(None, "--url", help="URL dbgs (override)."),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Подключить debug UI к dbgs (attachDebugUI)."""
    finish(
        run_attach(Path.cwd(), url=url, config_id=config, runtime_id=runtime),
        ctx,
        output,
    )


@app.command("detach")
def detach_cmd(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Отключить debug UI."""
    finish(
        run_detach(Path.cwd(), config_id=config, runtime_id=runtime),
        ctx,
        output,
    )


@app.command("force-detach")
def force_detach_cmd(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Принудительный detach + сброс session.json (recovery)."""
    finish(
        run_force_detach(Path.cwd(), config_id=config, runtime_id=runtime),
        ctx,
        output,
    )


@app.command("targets")
def targets_cmd(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Список debug targets."""
    finish(
        run_targets(Path.cwd(), config_id=config, runtime_id=runtime),
        ctx,
        output,
    )


@breakpoint_app.command("set")
def breakpoint_set_cmd(
    ctx: typer.Context,
    module: str | None = typer.Option(
        None,
        "--module",
        help="Имя модуля (например ОбщегоНазначения). Взаимоисключающе с --file.",
    ),
    module_type: str = typer.Option(
        "CommonModule",
        "--type",
        help="Тип модуля: CommonModule, ObjectModule, ManagedApplicationModule, …",
    ),
    file: Path | None = typer.Option(
        None,
        "--file",
        help=(
            "Путь к .bsl (например Catalogs/X/Ext/ObjectModule.bsl). "
            "Взаимоисключающе с --module."
        ),
    ),
    object_id: str | None = typer.Option(
        None,
        "--object-id",
        help="Явный objectID (escape; вместе с --property-id).",
    ),
    property_id: str | None = typer.Option(
        None,
        "--property-id",
        help="Явный propertyID (escape; вместе с --object-id).",
    ),
    lines: str = typer.Option(
        ...,
        "--lines",
        help="Номера строк через запятую (исполняемые).",
    ),
    extension: str | None = typer.Option(
        None,
        "--extension",
        help="Имя расширения (обязательно при неоднозначности).",
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Поставить точки останова: --module | --file | --object-id/--property-id."""
    parsed: list[int] = []
    for part in lines.split(","):
        part = part.strip()
        if not part:
            continue
        parsed.append(int(part))
    finish(
        run_breakpoint_set(
            Path.cwd(),
            module=module,
            module_type=module_type,
            lines=parsed,
            extension=extension,
            file=file,
            object_id=object_id,
            property_id=property_id,
            config_id=config,
            runtime_id=runtime,
        ),
        ctx,
        output,
    )


@breakpoint_app.command("clear")
def breakpoint_clear_cmd(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Снять все точки останова сессии."""
    finish(
        run_breakpoint_clear(Path.cwd(), config_id=config, runtime_id=runtime),
        ctx,
        output,
    )


@app.command("wait")
def wait_cmd(
    ctx: typer.Context,
    timeout: float = typer.Option(
        DEFAULT_WAIT_TIMEOUT_SEC,
        "--timeout",
        help="Таймаут ожидания остановки (секунды, default 30).",
    ),
    fresh: bool = typer.Option(
        False,
        "--fresh",
        help="Сбросить записанную остановку и ждать следующую.",
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Ждать остановку на breakpoint.

    По состоянию: если остановка уже записана — вернёт её сразу. Если клиент 1С
    завершился без остановки — быстро упадёт с 1CD016.
    """
    finish(
        run_wait(
            Path.cwd(),
            timeout=timeout,
            fresh=fresh,
            config_id=config,
            runtime_id=runtime,
        ),
        ctx,
        output,
    )


@app.command("continue")
def continue_cmd(
    ctx: typer.Context,
    target_id: str | None = typer.Option(None, "--target", help="targetId (default: last)."),
    timeout: float = typer.Option(
        DEFAULT_WAIT_TIMEOUT_SEC,
        "--timeout",
        help="Таймаут ожидания следующей остановки (секунды, default 30).",
    ),
    no_wait: bool = typer.Option(
        False,
        "--no-wait",
        help="Только отправить Continue, не ждать callStackFormed.",
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Continue — снять остановку; по умолчанию ждёт следующую (--no-wait для финала)."""
    finish(
        run_continue(
            Path.cwd(),
            target_id=target_id,
            wait=not no_wait,
            timeout=timeout,
            config_id=config,
            runtime_id=runtime,
        ),
        ctx,
        output,
    )


@app.command("step-in")
def step_in_cmd(
    ctx: typer.Context,
    target_id: str | None = typer.Option(None, "--target", help="targetId (default: last)."),
    timeout: float = typer.Option(
        DEFAULT_WAIT_TIMEOUT_SEC,
        "--timeout",
        help="Таймаут ожидания следующей остановки (секунды, default 30).",
    ),
    no_wait: bool = typer.Option(
        False,
        "--no-wait",
        help="Только отправить StepIn, не ждать callStackFormed.",
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """[EXPERIMENTAL / НЕ РАБОТАЕТ] StepIn — известный сбой 1CD005."""
    finish(
        run_step_in(
            Path.cwd(),
            target_id=target_id,
            wait=not no_wait,
            timeout=timeout,
            config_id=config,
            runtime_id=runtime,
        ),
        ctx,
        output,
    )


@app.command("step-over")
def step_over_cmd(
    ctx: typer.Context,
    target_id: str | None = typer.Option(None, "--target", help="targetId (default: last)."),
    timeout: float = typer.Option(
        DEFAULT_WAIT_TIMEOUT_SEC,
        "--timeout",
        help="Таймаут ожидания следующей остановки (секунды, default 30).",
    ),
    no_wait: bool = typer.Option(
        False,
        "--no-wait",
        help="Только отправить Step (step over), не ждать callStackFormed.",
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """[EXPERIMENTAL / НЕ РАБОТАЕТ] Step over — может завершаться 1CD005."""
    finish(
        run_step_over(
            Path.cwd(),
            target_id=target_id,
            wait=not no_wait,
            timeout=timeout,
            config_id=config,
            runtime_id=runtime,
        ),
        ctx,
        output,
    )


@app.command("step-out")
def step_out_cmd(
    ctx: typer.Context,
    target_id: str | None = typer.Option(None, "--target", help="targetId (default: last)."),
    timeout: float = typer.Option(
        DEFAULT_WAIT_TIMEOUT_SEC,
        "--timeout",
        help="Таймаут ожидания следующей остановки (секунды, default 30).",
    ),
    no_wait: bool = typer.Option(
        False,
        "--no-wait",
        help="Только отправить StepOut, не ждать callStackFormed.",
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """[EXPERIMENTAL / НЕ РАБОТАЕТ] StepOut — может завершаться 1CD005."""
    finish(
        run_step_out(
            Path.cwd(),
            target_id=target_id,
            wait=not no_wait,
            timeout=timeout,
            config_id=config,
            runtime_id=runtime,
        ),
        ctx,
        output,
    )


@app.command("pause")
def pause_cmd(
    ctx: typer.Context,
    timeout: float = typer.Option(
        DEFAULT_WAIT_TIMEOUT_SEC,
        "--timeout",
        help="Таймаут ожидания остановки (секунды, default 30).",
    ),
    no_wait: bool = typer.Option(
        False,
        "--no-wait",
        help="Только включить breakOnNextLine, не ждать stop.",
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """[EXPERIMENTAL / НЕ РАБОТАЕТ] Pause (breakOnNextLine)."""
    finish(
        run_pause(
            Path.cwd(),
            wait=not no_wait,
            timeout=timeout,
            config_id=config,
            runtime_id=runtime,
        ),
        ctx,
        output,
    )


@app.command("stack")
def stack_cmd(
    ctx: typer.Context,
    target_id: str | None = typer.Option(None, "--target", help="targetId (default: last stop)."),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Стек вызовов с последней остановки."""
    finish(
        run_stack(
            Path.cwd(), target_id=target_id, config_id=config, runtime_id=runtime
        ),
        ctx,
        output,
    )


@app.command("variables")
def variables_cmd(
    ctx: typer.Context,
    target_id: str | None = typer.Option(None, "--target", help="targetId (default: last stop)."),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Локальные переменные (evalLocalVariables)."""
    finish(
        run_variables(
            Path.cwd(), target_id=target_id, config_id=config, runtime_id=runtime
        ),
        ctx,
        output,
    )


@app.command("eval")
def eval_cmd(
    ctx: typer.Context,
    expression: str = typer.Argument(..., help="Выражение BSL для evalExpr."),
    target_id: str | None = typer.Option(None, "--target", help="targetId (default: last stop)."),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Вычислить выражение (evalExpr)."""
    finish(
        run_evaluate(
            Path.cwd(),
            expression=expression,
            target_id=target_id,
            config_id=config,
            runtime_id=runtime,
        ),
        ctx,
        output,
    )


@app.command("status")
def status_cmd(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Сводка: server + session + client.meta debug.enabled."""
    finish(
        run_status(Path.cwd(), config_id=config, runtime_id=runtime),
        ctx,
        output,
    )


@app.command("reload-metadata")
def reload_metadata_cmd(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Пересобрать UUID↔module cache из XML source."""
    finish(
        run_reload_metadata(Path.cwd(), config_id=config, runtime_id=runtime),
        ctx,
        output,
    )


@ping_app.command("start")
def ping_start_cmd(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Запустить background ping (держит stopped target между командами)."""
    finish(
        run_ping_start(Path.cwd(), config_id=config, runtime_id=runtime),
        ctx,
        output,
    )


@ping_app.command("stop")
def ping_stop_cmd(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Остановить background ping."""
    finish(
        run_ping_stop(Path.cwd(), config_id=config, runtime_id=runtime),
        ctx,
        output,
    )


@ping_app.command("status")
def ping_status_cmd(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Статус background ping."""
    finish(
        run_ping_status(Path.cwd(), config_id=config, runtime_id=runtime),
        ctx,
        output,
    )
