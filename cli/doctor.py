"""CLI: 1c-dev doctor."""

from __future__ import annotations

import json
from typing import Any

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from core.doctor import DoctorResult, run_doctor
from core.exit_codes import ENV_UNAVAILABLE, SUCCESS
from core.toolchain.result import SyncResult
from core.toolchain.sync import sync_tools

_TOOL_ORDER = (
    "cli",
    "ibcmd",
    "1cv8",
    "java",
    "xml-gen",
    "md-reader",
    "bsl-language-server",
    "docs-facade",
)


def _mark(ok: bool) -> str:
    return "✓" if ok else "✗"


def _tool_line(name: str, info: dict[str, Any]) -> list[str]:
    lines: list[str] = [f"{name}:"]
    if info.get("found") and info.get("path"):
        extra: list[str] = []
        if info.get("version"):
            extra.append(f"v{info['version']}")
        if info.get("source"):
            extra.append(str(info["source"]))
        suffix = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"  {info['path']}{suffix} {_mark(True)}")
    elif info.get("found"):
        lines.append(f"  found {_mark(True)}")
    else:
        lines.append(f"  not found {_mark(False)}")
    return lines


def _text_report(result: DoctorResult) -> list[str]:
    platform = result.platform

    if platform.get("found"):
        version = platform.get("version") or "unknown"
        path = platform.get("path")
        if path:
            platform_line = f"  {version} ({path}) {_mark(True)}"
        else:
            platform_line = f"  {version} {_mark(True)}"
    else:
        platform_line = f"  not found {_mark(False)}"

    lines = [
        "1C Dev Runtime",
        "",
        "Platform:",
        platform_line,
    ]
    for name in _TOOL_ORDER:
        tool = result.tools.get(name)
        if tool is None:
            continue
        lines.extend(_tool_line(name, tool))

    lines.append("")
    lines.append("Capabilities:")
    for name, cap in result.capabilities.items():
        if cap["available"]:
            lines.append(f"  {name}: available {_mark(True)}")
        else:
            missing = ", ".join(cap["requires"])
            lines.append(f"  {name}: unavailable (нужен {missing}) {_mark(False)}")
        types = cap.get("supportedTypes")
        if types:
            lines.append(f"    types: {', '.join(types)}")

    if result.diagnostics:
        lines.append("")
        lines.append("Diagnostics:")
        for diag in result.diagnostics:
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            sev = diag.get("severity", "info")
            lines.append(f"  {sev}: {prefix}{diag.get('message', '')}")
            suggestion = diag.get("suggestion")
            if suggestion:
                lines.append(f"    → {suggestion}")

    return lines


def _text_sync(result: SyncResult) -> list[str]:
    lines = ["Toolchain sync (doctor --fix)", "", "Components:"]
    for comp in result.components:
        path = f" ({comp.path})" if comp.path else ""
        pin = f" [{comp.pin}]" if comp.pin else ""
        msg = f" — {comp.message}" if comp.message else ""
        lines.append(f"  {comp.id}: {comp.status}{pin}{path}{msg}")
    lines.append("")
    lines.append(f"Sync status: {result.status}")
    return lines


def doctor_command(
    ctx: typer.Context,
    output: OutputOption = None,
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Скачать/собрать jars toolchain (tools sync), затем повторить проверку.",
    ),
) -> None:
    """Диагностика окружения: CLI, jars toolchain, Java, платформа, ibcmd."""
    fmt = resolve_output(ctx, output)
    sync_result: SyncResult | None = None

    if fix:
        live = fmt is not OutputFormat.json

        def progress(message: str) -> None:
            typer.echo(message, err=True)

        sync_result = sync_tools(
            progress=progress if live else None,
            quiet=not live,
        )

    result = run_doctor()

    if fmt is OutputFormat.json:
        payload: dict[str, Any] = result.to_payload()
        if sync_result is not None:
            payload = {
                "fix": sync_result.to_payload(),
                "doctor": payload,
            }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if sync_result is not None:
            for line in _text_sync(sync_result):
                typer.echo(line)
            typer.echo("")
        for line in _text_report(result):
            typer.echo(line)

    if sync_result is not None and sync_result.status == "error":
        raise typer.Exit(code=ENV_UNAVAILABLE)
    code = SUCCESS if result.status == "ok" else ENV_UNAVAILABLE
    raise typer.Exit(code=code)
