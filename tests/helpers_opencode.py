"""Helpers for OpenCode + local LLM integration tests (single-stream safe)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / ".opencode-it"
ENV_LOCAL = REPO_ROOT / ".patterns-ab" / "env.local"
LLM_LOCK = DATA_ROOT / "llm.lock"


def load_llm_env(env_file: Path | None = None) -> dict[str, str]:
    """Parse KEY=VALUE / export KEY=VALUE from env.local into a dict."""
    path = env_file or ENV_LOCAL
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith("'") and val.endswith("'")) or (
            val.startswith('"') and val.endswith('"')
        ):
            val = val[1:-1]
        # Expand $VAR using already-parsed keys + os.environ
        for k, v in {**os.environ, **out}.items():
            val = val.replace(f"${{{k}}}", v).replace(f"${k}", v)
        out[key] = val
    return out


def llm_ready() -> tuple[bool, str]:
    """Return (ok, reason). Requires env.local + opencode + LLM_*."""
    if shutil.which("opencode") is None:
        return False, "opencode не найден в PATH"
    env = load_llm_env()
    if not env.get("LLM_BASE_URL") or not env.get("LLM_API_KEY"):
        return False, f"нет LLM_BASE_URL/LLM_API_KEY в {ENV_LOCAL}"
    if not env.get("LLM_MODEL"):
        return False, f"нет LLM_MODEL в {ENV_LOCAL}"
    return True, "ok"


@contextmanager
def llm_stream_lock(timeout_sec: float = 3600.0) -> Iterator[None]:
    """Exclusive lock: local LLM accepts only one concurrent stream."""
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    lock_path = LLM_LOCK
    deadline = time.time() + timeout_sec
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, f"{os.getpid()} {time.time()}\n".encode())
            os.close(fd)
            break
        except FileExistsError:
            if time.time() >= deadline:
                raise TimeoutError(f"LLM lock busy: {lock_path}") from None
            # Stale lock from dead pid?
            try:
                text = lock_path.read_text(encoding="utf-8").strip().split()
                if text:
                    pid = int(text[0])
                    os.kill(pid, 0)
            except (ValueError, ProcessLookupError, PermissionError, OSError):
                try:
                    lock_path.unlink(missing_ok=True)
                    continue
                except OSError:
                    pass
            time.sleep(2.0)
    try:
        yield
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def _cognitum_provider(env: dict[str, str]) -> dict[str, Any] | None:
    base = env.get("LLM_BASE_URL") or env.get("OPENAI_BASE_URL")
    model = env.get("LLM_MODEL")
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


def write_opencode_config(workspace: Path, *, steps: int | None = None) -> str:
    """Write opencode.json with 1c-dev MCP + cognitum provider. Return model id."""
    env = load_llm_env()
    poetry = shutil.which("poetry") or "poetry"
    steps_n = steps
    if steps_n is None:
        raw = env.get("PATTERNS_AB_STEPS") or env.get("OPENCODE_STEPS") or "40"
        try:
            steps_n = max(1, int(raw))
        except ValueError:
            steps_n = 40
    cfg: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "1c-dev": {
                "type": "local",
                "command": [poetry, "-C", str(REPO_ROOT), "run", "1c-dev", "mcp"],
                "enabled": True,
            }
        },
        "agent": {"build": {"steps": steps_n}},
    }
    provider = _cognitum_provider(env)
    model_id = env.get("PATTERNS_AB_MODEL") or ""
    if provider:
        cfg["provider"] = {"cognitum": provider}
        model = env.get("LLM_MODEL")
        if model:
            model_id = model_id or f"cognitum/{model}"
            cfg["model"] = model_id
    (workspace / "opencode.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not model_id:
        raise ValueError("PATTERNS_AB_MODEL / LLM_MODEL не заданы")
    return model_id


def prepare_workspace(
    run_dir: Path,
    *,
    name: str = "MetaIt",
    config: str = "MetaIt",
    prompt: str,
    steps: int | None = None,
) -> Path:
    """Init empty 1c-dev project under run_dir/workspace and write prompt + opencode.json."""
    run_dir.mkdir(parents=True, exist_ok=True)
    workspace = run_dir / "workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    cmd = [
        "poetry",
        "-C",
        str(REPO_ROOT),
        "run",
        "1c-dev",
        "init",
        "--type",
        "configuration",
        "--name",
        name,
        "--config",
        config,
        "--ide-target",
        "none",
    ]
    subprocess.run(cmd, cwd=workspace, check=True)
    (run_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    model_id = write_opencode_config(workspace, steps=steps)
    (run_dir / "model.txt").write_text(model_id + "\n", encoding="utf-8")
    return workspace


def _tee_jsonl(stdout: Any, jsonl_path: Path, transcript_path: Path) -> None:
    """Minimal JSONL tee + rough transcript (tool names)."""
    transcript_path.write_text(
        f"# Agent transcript\n\nSource: `{jsonl_path}`\n\n",
        encoding="utf-8",
    )
    with jsonl_path.open("w", encoding="utf-8") as jf, transcript_path.open(
        "a", encoding="utf-8"
    ) as tf:
        for line in stdout:
            jf.write(line)
            jf.flush()
            s = line.strip()
            if not s:
                continue
            try:
                ev = json.loads(s)
            except json.JSONDecodeError:
                continue
            part = ev.get("part") or {}
            t = ev.get("type")
            if t == "text" or part.get("type") == "text":
                text = (part.get("text") or "").strip()
                if text:
                    tf.write(f"\n### model\n\n{text}\n")
                    tf.flush()
            elif t == "tool_use" or part.get("type") == "tool":
                name = part.get("tool") or "?"
                st = part.get("state") or {}
                status = st.get("status") or "?"
                inp = st.get("input") or {}
                qn = inp.get("qualified_name") or inp.get("query") or ""
                tf.write(f"\n- **tool** `{name}` [{status}] {qn}\n")
                err = st.get("error")
                if err:
                    tf.write(f"  ERROR: {err!s}\n")
                tf.flush()


def _build_opencode_env(env_file: dict[str, str]) -> dict[str, str]:
    """Minimal env for OpenCode + Cognitum (polluted poetry/nvm env breaks LLM)."""
    # Prefer system+nvm node path; avoid poetry venv shadowing node tooling.
    path_parts = [
        str(Path.home() / ".nvm/versions/node/v22.21.0/bin"),
        str(Path.home() / ".local/bin"),
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    # Keep existing PATH entries that look like node/opencode homes.
    for part in (os.environ.get("PATH") or "").split(":"):
        if not part or part in path_parts:
            continue
        if "node" in part or "nvm" in part or part.endswith("/bin"):
            if ".cache/pypoetry" in part or "virtualenvs" in part:
                continue
            path_parts.append(part)
    proc_env: dict[str, str] = {
        "HOME": str(Path.home()),
        "USER": os.environ.get("USER") or "user",
        "LANG": os.environ.get("LANG") or "C.UTF-8",
        "PATH": ":".join(path_parts),
        "TERM": os.environ.get("TERM") or "xterm-256color",
    }
    proc_env.update(env_file)
    if env_file.get("LLM_API_KEY"):
        proc_env["OPENAI_API_KEY"] = env_file["LLM_API_KEY"]
        proc_env["LLM_API_KEY"] = env_file["LLM_API_KEY"]
    if env_file.get("LLM_BASE_URL"):
        proc_env["OPENAI_BASE_URL"] = env_file["LLM_BASE_URL"]
        proc_env["LLM_BASE_URL"] = env_file["LLM_BASE_URL"]
    proc_env["NODE_USE_ENV_PROXY"] = env_file.get("NODE_USE_ENV_PROXY") or "1"
    proc_env["NODE_TLS_REJECT_UNAUTHORIZED"] = (
        env_file.get("NODE_TLS_REJECT_UNAUTHORIZED") or "0"
    )
    return proc_env


def _jsonl_has_unexpected_server_error(jsonl_path: Path) -> bool:
    if not jsonl_path.is_file():
        return False
    text = jsonl_path.read_text(encoding="utf-8", errors="replace")
    return "Unexpected server error" in text


def run_opencode(
    run_dir: Path,
    *,
    model: str | None = None,
    title: str | None = None,
    timeout_sec: float | None = 1800.0,
    retries: int = 2,
) -> int:
    """Run `opencode run` under LLM lock. Return process exit code."""
    workspace = run_dir / "workspace"
    prompt_path = run_dir / "prompt.md"
    if not workspace.is_dir() or not prompt_path.is_file():
        raise FileNotFoundError(f"need workspace/ and prompt.md in {run_dir}")

    env_file = load_llm_env()
    model_id = (
        model
        or env_file.get("PATTERNS_AB_MODEL")
        or (run_dir / "model.txt").read_text(encoding="utf-8").strip()
    )
    prompt_text = prompt_path.read_text(encoding="utf-8")
    jsonl = run_dir / "agent.jsonl"
    transcript = run_dir / "agent.transcript.md"
    stderr_path = run_dir / "agent.stderr.log"
    meta = run_dir / "run-meta.txt"
    proc_env = _build_opencode_env(env_file)

    code = 1
    attempt = 0
    while attempt <= max(0, retries):
        attempt += 1
        title_s = title or f"opencode-it-{run_dir.name}-{int(time.time())}-{attempt}"
        meta.write_text(
            f"started {datetime.now(UTC).astimezone().isoformat()}\n"
            f"model {model_id}\n"
            f"title {title_s}\n"
            f"attempt {attempt}\n",
            encoding="utf-8",
        )
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
        with llm_stream_lock():
            with stderr_path.open("w", encoding="utf-8") as errf:
                proc = subprocess.Popen(
                    cmd,
                    cwd=workspace,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=errf,
                    text=True,
                    bufsize=1,
                    env=proc_env,
                )
                assert proc.stdout is not None
                try:
                    _tee_jsonl(proc.stdout, jsonl, transcript)
                    code = proc.wait(timeout=timeout_sec)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    code = 124
                    with meta.open("a", encoding="utf-8") as mf:
                        mf.write("timeout\n")
        with meta.open("a", encoding="utf-8") as mf:
            mf.write(
                f"exit={code} finished "
                f"{datetime.now(UTC).astimezone().isoformat()}\n"
            )
        if code == 0 or not _jsonl_has_unexpected_server_error(jsonl):
            break
        # Cognitum transient: wait before single-stream retry
        time.sleep(3.0 * attempt)

    (run_dir / "finished.txt").write_text(f"exit={code}\n", encoding="utf-8")
    return int(code)


def new_run_dir(scenario: str) -> Path:
    """Create timestamped run directory under .opencode-it/runs/."""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in scenario)
    path = DATA_ROOT / "runs" / f"{safe}-{ts}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def find_metadata_file(workspace: Path, *parts: str) -> Path | None:
    """Find a metadata file under workspace/src (XML or EDT layout)."""
    src = workspace / "src"
    if not src.is_dir():
        return None
    matches = list(src.rglob(parts[-1])) if parts else []
    # Prefer exact relative suffix match
    suffix = Path(*parts)
    for p in src.rglob("*"):
        try:
            if p.relative_to(src).as_posix().endswith(suffix.as_posix()):
                return p
        except ValueError:
            continue
    return matches[0] if matches else None


def assert_object_exists(workspace: Path, kind_folder: str, name: str) -> Path:
    """Assert Catalogs/Name.xml or EDT Name/Name.mdo exists; return path."""
    # Designer XML
    for p in (workspace / "src").rglob(f"{kind_folder}/{name}.xml"):
        return p
    # EDT
    for p in (workspace / "src").rglob(f"{kind_folder}/{name}/{name}.mdo"):
        return p
    raise AssertionError(
        f"не найден объект {kind_folder}/{name} под {workspace / 'src'}"
    )


def file_contains(path: Path, *needles: str) -> bool:
    text = path.read_text(encoding="utf-8")
    return all(n in text for n in needles)
