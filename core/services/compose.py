"""Thin docker compose adapter for a single installed tool (Этап 1)."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.diagnostics import Diagnostic, error
from core.tools.catalog import ToolRecipe

ProgressCb = Callable[[str], None] | None


@dataclass(frozen=True)
class ComposeCommandResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    diagnostics: list[Diagnostic]


def docker_available() -> bool:
    return shutil.which("docker") is not None


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _compose_base(tool_dir: Path, recipe: ToolRecipe) -> list[str]:
    compose = tool_dir / recipe.compose_file
    cmd = [
        "docker",
        "compose",
        "--project-directory",
        str(tool_dir),
        "-f",
        str(compose),
        "-p",
        recipe.project_name,
    ]
    for profile in recipe.profiles:
        cmd.extend(["--profile", profile])
    return cmd


def run_compose(
    tool_dir: Path,
    recipe: ToolRecipe,
    args: list[str],
    *,
    progress: ProgressCb = None,
) -> ComposeCommandResult:
    if not docker_available():
        return ComposeCommandResult(
            ok=False,
            returncode=127,
            stdout="",
            stderr="",
            diagnostics=[
                error(
                    "docker не найден в PATH",
                    code="1CX003",
                    source="services",
                    suggestion="Установите Docker / Docker Compose",
                )
            ],
        )
    compose_path = tool_dir / recipe.compose_file
    if not compose_path.is_file():
        return ComposeCommandResult(
            ok=False,
            returncode=1,
            stdout="",
            stderr="",
            diagnostics=[
                error(
                    f"compose file не найден: {recipe.compose_file}",
                    code="1CX007",
                    source="services",
                )
            ],
        )
    cmd = _compose_base(tool_dir, recipe) + args
    if progress:
        progress(" ".join(cmd))
    env = {**os.environ, "COMPOSE_PROJECT_NAME": recipe.project_name}
    completed = subprocess.run(
        cmd,
        cwd=str(tool_dir),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        msg = f"docker compose {' '.join(args)} failed (exit {completed.returncode})"
        if detail:
            msg = f"{msg}: {detail[:500]}"
        return ComposeCommandResult(
            ok=False,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            diagnostics=[
                error(
                    msg,
                    code="1CX006",
                    source="services",
                    suggestion="1c-dev services logs " + recipe.id,
                )
            ],
        )
    return ComposeCommandResult(
        ok=True,
        returncode=0,
        stdout=completed.stdout,
        stderr=completed.stderr,
        diagnostics=[],
    )
