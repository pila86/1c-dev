"""CLI: 1c-dev doctor."""

from __future__ import annotations

import json
from typing import Any

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from core.doctor import DoctorResult, run_doctor
from core.exit_codes import ENV_UNAVAILABLE, SUCCESS


def _mark(ok: bool) -> str:
    return "✓" if ok else "✗"


def _text_report(result: DoctorResult) -> list[str]:
    platform = result.platform
    ibcmd = result.tools["ibcmd"]
    onecv8 = result.tools["1cv8"]

    if platform.get("found"):
        version = platform.get("version") or "unknown"
        path = platform.get("path")
        if path:
            platform_line = f"  {version} ({path}) {_mark(True)}"
        else:
            platform_line = f"  {version} {_mark(True)}"
    else:
        platform_line = f"  not found {_mark(False)}"

    def tool_line(info: dict[str, Any]) -> str:
        if info.get("found") and info.get("path"):
            return f"  {info['path']} {_mark(True)}"
        return f"  not found {_mark(False)}"

    lines = [
        "1C Dev Runtime",
        "",
        "Platform:",
        platform_line,
        "ibcmd:",
        tool_line(ibcmd),
        "1cv8:",
        tool_line(onecv8),
        "java:",
        tool_line(result.tools["java"]),
        "xml-gen:",
        tool_line(result.tools["xml-gen"]),
        "",
        "Capabilities:",
    ]
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


def doctor_command(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """Диагностика окружения: платформа, ibcmd, 1cv8, capability gaps."""
    result = run_doctor()
    fmt = resolve_output(ctx, output)
    if fmt is OutputFormat.json:
        typer.echo(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
    else:
        for line in _text_report(result):
            typer.echo(line)

    code = SUCCESS if result.status == "ok" else ENV_UNAVAILABLE
    raise typer.Exit(code=code)
