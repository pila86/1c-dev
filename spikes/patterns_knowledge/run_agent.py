"""Launch OpenCode A/B run and write agent.jsonl + agent.transcript.md."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import typer

from patterns_knowledge.paths import ensure_data_dirs
from patterns_knowledge.transcript import tee_jsonl_to_transcript, write_transcript

app = typer.Typer(
    help="Run OpenCode on a prepared A/B workspace with transcript.",
    invoke_without_command=True,
)


def execute_agent_run(
    run_dir: Path,
    *,
    model: str | None = None,
    title: str | None = None,
) -> int:
    """Run opencode; return process exit code. Writes agent.jsonl + agent.transcript.md."""
    ensure_data_dirs()
    run_dir = run_dir.resolve()
    workspace = run_dir / "workspace"
    prompt = run_dir / "prompt.md"
    if not workspace.is_dir():
        raise FileNotFoundError(f"no workspace: {workspace}")
    if not prompt.is_file():
        raise FileNotFoundError(f"no prompt: {prompt}")

    model_id = model or os.environ.get("PATTERNS_AB_MODEL") or ""
    if not model_id and os.environ.get("LLM_MODEL"):
        model_id = f"cognitum/{os.environ['LLM_MODEL']}"
    if not model_id:
        cfg_path = workspace / "opencode.json"
        if cfg_path.is_file():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            model_id = str(cfg.get("model") or "")
    if not model_id:
        raise ValueError("set --model or PATTERNS_AB_MODEL")

    jsonl = run_dir / "agent.jsonl"
    transcript = run_dir / "agent.transcript.md"
    stderr_path = run_dir / "agent.stderr.log"
    meta = run_dir / "run-meta.txt"
    (run_dir / "model.txt").write_text(model_id + "\n", encoding="utf-8")
    steps = os.environ.get("PATTERNS_AB_STEPS") or "?"
    meta.write_text(
        f"started {datetime.now(timezone.utc).astimezone().isoformat()}\n"
        f"model {model_id}\n"
        f"steps_limit {steps}\n"
        f"proxy {os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY') or ''}\n",
        encoding="utf-8",
    )
    transcript.write_text(
        f"# Agent transcript\n\n"
        f"Source: `{jsonl}`\n"
        f"Model: `{model_id}`\n"
        f"Steps limit: `{steps}`\n\n",
        encoding="utf-8",
    )

    prompt_text = prompt.read_text(encoding="utf-8")
    # Unique title avoids OpenCode session reuse after a failed Cognitum probe.
    title_s = title or f"patterns-ab-{run_dir.name}-{int(time.time())}"
    cmd = [
        "opencode",
        "run",
        "--auto",
        "-m",
        model_id,
        "--format",
        "json",
        "--title",
        title_s,
        prompt_text,
    ]
    typer.echo(f"running: {' '.join(cmd[:8])} … → {jsonl.name} + {transcript.name}")
    env = os.environ.copy()
    # Cognitum via corporate proxy often needs these; keep explicit for poetry children.
    env.setdefault("NODE_USE_ENV_PROXY", "1")
    with stderr_path.open("w", encoding="utf-8") as errf:
        proc = subprocess.Popen(
            cmd,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=errf,
            text=True,
            bufsize=1,
            env=env,
            start_new_session=True,
        )
        assert proc.stdout is not None
        tee_jsonl_to_transcript(proc.stdout, jsonl, transcript, include_tools=True)
        code = proc.wait()
    write_transcript(jsonl, transcript, include_tools=True)
    with meta.open("a", encoding="utf-8") as mf:
        mf.write(
            f"exit={code} finished {datetime.now(timezone.utc).astimezone().isoformat()}\n"
            f"title {title_s}\n"
        )
    return int(code)


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    run_dir: Path = typer.Argument(
        ...,
        help="Run root, e.g. .patterns-ab/runs/A-…",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="provider/model (default: PATTERNS_AB_MODEL or opencode.json model)",
    ),
    title: str | None = typer.Option(None, "--title"),
) -> None:
    """Run opencode in workspace/; stream JSONL + human transcript."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        code = execute_agent_run(run_dir, model=model, title=title)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e
    raise typer.Exit(code)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
