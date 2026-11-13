"""Prepare A/B workspaces for the Larek coding-patterns experiment."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import typer

from patterns_knowledge.paths import DATA_ROOT, REPO_ROOT, ensure_data_dirs

app = typer.Typer(help="Create run workspaces for patterns A/B.", invoke_without_command=True)

PROMPT = """Ты разрабатываешь конфигурацию 1С:Предприятие в этом workspace через доступные MCP-инструменты.

Задача: конфигурация «Ларёк».
1) Справочник «Товары».
2) Регистр накопления остатков товаров (вид Остатки): измерение — товар (ссылка на Товары), ресурс — количество.
3) Документ «Оприходование товаров» с табличной частью (товар, количество) и проведением, которое делает приход по регистру остатков.

Требования:
- Используй MCP 1c-dev для проекта и метаданных (project/configuration/metadata/build/check), не Конфигуратор и не выдуманные CLI платформы.
- Не выдумывай API платформы: уточняй через docs.* / language server, если доступны.
- После создания объектов реализуй модуль проведения документа.
- Добийся успешного build и check.
- Кратко в конце перечисли созданные объекты метаданных и где лежит код проведения.

Не реализуй склады, цены, расход и тесты, если это не нужно для проведения.
"""

AGENTS_PATTERNS = """
## Patterns knowledge (treatment B only)
- Прикладной паттерн BSL (проведение, регистры, транзакции, строки) → MCP `patterns.search` / `patterns.get`, не выдумывать.
- Сборка, ИБ, метаданные объектов → MCP `1c-dev`.
- Имя платформенного API → `docs.*` / bsl-ls.
"""


def _poetry_1c(*args: str, cwd: Path) -> None:
    cmd = ["poetry", "-C", str(REPO_ROOT), "run", "1c-dev", *args]
    subprocess.run(cmd, cwd=cwd, check=True)


def _cognitum_provider() -> dict | None:
    """Optional OpenAI-compatible provider from env.local (LLM_*)."""
    base = os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    model = os.environ.get("LLM_MODEL")
    if not base or not model:
        return None
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Cognitum",
        "env": ["LLM_API_KEY", "OPENAI_API_KEY"],
        "options": {
            "baseURL": base.rstrip("/"),
            "apiKey": "{env:LLM_API_KEY}",
        },
        "models": {
            model: {
                "name": model,
                "tools": True,
                "limit": {"context": 262144, "output": 16384},
            }
        },
    }


def _agent_steps() -> int:
    """Max OpenCode agentic steps (model turns). Env PATTERNS_AB_STEPS, default 40."""
    raw = os.environ.get("PATTERNS_AB_STEPS") or os.environ.get("OPENCODE_STEPS") or "40"
    try:
        n = int(raw)
    except ValueError:
        n = 40
    return max(1, n)


def _write_opencode_mcp(workspace: Path, *, with_patterns: bool) -> None:
    poetry = shutil.which("poetry") or "poetry"
    servers = {
        "1c-dev": {
            "type": "local",
            "command": [poetry, "-C", str(REPO_ROOT), "run", "1c-dev", "mcp"],
            "enabled": True,
        }
    }
    if with_patterns:
        servers["patterns"] = {
            "type": "local",
            "command": [
                poetry,
                "-C",
                str(REPO_ROOT),
                "run",
                "patterns-knowledge",
                "mcp",
            ],
            "enabled": True,
        }
    steps = _agent_steps()
    cfg: dict = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": servers,
        # Limit wheel-spinning: on final step OpenCode forces text-only summary.
        "agent": {
            "build": {
                "steps": steps,
            }
        },
    }
    provider = _cognitum_provider()
    if provider:
        cfg["provider"] = {"cognitum": provider}
        model = os.environ.get("LLM_MODEL")
        if model:
            cfg["model"] = f"cognitum/{model}"
    (workspace / "opencode.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@app.command()
def prepare(
    run: str = typer.Argument(..., help="A or B"),
    stamp: str | None = typer.Option(None, help="Timestamp folder suffix"),
) -> None:
    """Init empty Larek workspace under .patterns-ab/runs/."""

    ensure_data_dirs()
    run_u = run.strip().upper()
    if run_u not in {"A", "B"}:
        raise typer.BadParameter("run must be A or B")
    ts = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = DATA_ROOT / "runs" / f"{run_u}-{ts}"
    workspace = root / "workspace"
    if workspace.exists():
        raise typer.Exit(f"exists: {workspace}")
    workspace.mkdir(parents=True)
    _poetry_1c(
        "init",
        "--type",
        "configuration",
        "--name",
        "Larek",
        "--config",
        "Larek",
        "--ide-target",
        "none",
        cwd=workspace,
    )
    (root / "prompt.md").write_text(PROMPT, encoding="utf-8")
    agents = workspace / "AGENTS.md"
    text = agents.read_text(encoding="utf-8") if agents.is_file() else ""
    if run_u == "B":
        if "patterns.search" not in text:
            agents.write_text(text.rstrip() + "\n" + AGENTS_PATTERNS, encoding="utf-8")
        _write_opencode_mcp(workspace, with_patterns=True)
    else:
        _write_opencode_mcp(workspace, with_patterns=False)
    # git baseline
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline: empty Larek scope"],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    typer.echo(str(root))


if __name__ == "__main__":
    app()
