"""Process runtime adapter for managed external tools (ADR-033 Этап 7)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from adapters.platform_1cv8.process import is_running, terminate
from core.diagnostics import Diagnostic, error, info, warning
from core.tools.catalog import ToolRecipe
from core.tools.install import expand_template, resolve_env_vars
from core.tools.paths import data_share_dir, installed_tool_dir

ProgressCb = Callable[[str], None] | None


def process_runtime_dir(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    """PID/log directory under share data (not cache)."""
    return data_share_dir(env=env, platform=platform) / tool_id / "runtime"


def pid_file(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    return process_runtime_dir(tool_id, env=env, platform=platform) / "service.pid"


def log_file(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    return process_runtime_dir(tool_id, env=env, platform=platform) / "service.log"


def read_pid(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> int | None:
    path = pid_file(tool_id, env=env, platform=platform)
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_pid(
    tool_id: str,
    pid: int,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> None:
    root = process_runtime_dir(tool_id, env=env, platform=platform)
    root.mkdir(parents=True, exist_ok=True)
    pid_file(tool_id, env=env, platform=platform).write_text(f"{pid}\n", encoding="utf-8")


def clear_pid(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> None:
    path = pid_file(tool_id, env=env, platform=platform)
    path.unlink(missing_ok=True)


def alive_pid(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> int | None:
    pid = read_pid(tool_id, env=env, platform=platform)
    if pid is None:
        return None
    if is_running(pid):
        return pid
    clear_pid(tool_id, env=env, platform=platform)
    return None


def _expand_argv(argv: Sequence[str], env_vars: dict[str, str]) -> list[str]:
    return [expand_template(str(arg), env_vars) for arg in argv]


def resolve_process_argv(
    recipe: ToolRecipe,
    tool_dir: Path,
    *,
    environ: dict[str, str] | None = None,
) -> tuple[list[str] | None, list[Diagnostic]]:
    """Build argv from ``runtime.argv`` with env expansion."""
    diags: list[Diagnostic] = []
    env_vars = resolve_env_vars(tool_dir, environ=environ)
    # Allow process env overlay for JAVA / jar overrides beyond known keys.
    base = environ if environ is not None else os.environ
    for key in ("JAVA", "JAVA_HOME", "ONEC_BSLLS_JAR", "BSLLS_JAR"):
        if key in base and base[key]:
            env_vars[key] = base[key]
    if "JAVA" not in env_vars:
        java_home = env_vars.get("JAVA_HOME") or base.get("JAVA_HOME")
        if java_home:
            java_name = "java.exe" if sys.platform == "win32" else "java"
            candidate = Path(java_home) / "bin" / java_name
            if candidate.is_file():
                env_vars["JAVA"] = str(candidate)
        if "JAVA" not in env_vars:
            env_vars["JAVA"] = "java"

    # ONEC_BSLLS_JAR → BSLLS_JAR for recipes that use the latter.
    if env_vars.get("ONEC_BSLLS_JAR") and not env_vars.get("BSLLS_JAR"):
        env_vars["BSLLS_JAR"] = env_vars["ONEC_BSLLS_JAR"]

    raw_argv = recipe.runtime.get("argv")
    if not isinstance(raw_argv, list) or not raw_argv:
        diags.append(
            error(
                "runtime.argv не задан для process recipe",
                code="1CX007",
                source="services",
            )
        )
        return None, diags

    argv = _expand_argv([str(a) for a in raw_argv], env_vars)
    # Resolve relative jar paths against tool_dir.
    for i, arg in enumerate(argv):
        if arg.endswith(".jar") and not Path(arg).is_absolute():
            candidate = (tool_dir / arg).resolve()
            if candidate.is_file():
                argv[i] = str(candidate)
    return argv, diags


def start_process(
    tool_id: str,
    recipe: ToolRecipe,
    *,
    progress: ProgressCb = None,
    environ: dict[str, str] | None = None,
) -> tuple[bool, list[Diagnostic]]:
    """Start managed process; write pid + log under data share."""
    diags: list[Diagnostic] = []
    existing = alive_pid(tool_id)
    if existing is not None:
        diags.append(
            info(
                f"process уже запущен (pid={existing})",
                code="1CX000",
                source="services",
            )
        )
        return True, diags

    tool_dir = installed_tool_dir(tool_id)
    argv, argv_diags = resolve_process_argv(recipe, tool_dir, environ=environ)
    diags.extend(argv_diags)
    if argv is None:
        return False, diags

    # Fail fast if jar missing.
    for arg in argv:
        if arg.endswith(".jar") and not Path(arg).is_file():
            diags.append(
                error(
                    f"jar не найден: {arg}",
                    code="1CX006",
                    source="services",
                    suggestion="1c-dev tools install bsl-ls или задайте ONEC_BSLLS_JAR",
                )
            )
            return False, diags

    runtime_dir = process_runtime_dir(tool_id)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_file(tool_id)
    if progress:
        progress(f"Запуск process {tool_id}: {' '.join(argv[:4])}…")

    try:
        log_handle = log_path.open("ab")
    except OSError as exc:
        diags.append(
            error(f"не удалось открыть лог {log_path}: {exc}", code="1CX006", source="services")
        )
        return False, diags

    try:
        # Detach from parent session; keep stdout/stderr in log.
        if sys.platform == "win32":
            proc = subprocess.Popen(  # noqa: S603 — argv from recipe+env
                argv,
                cwd=str(tool_dir),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,  # type: ignore[attr-defined]
            )
        else:
            proc = subprocess.Popen(  # noqa: S603 — argv from recipe+env
                argv,
                cwd=str(tool_dir),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
    except OSError as exc:
        log_handle.close()
        diags.append(
            error(f"не удалось запустить process: {exc}", code="1CX006", source="services")
        )
        return False, diags
    finally:
        # Child holds the fd; parent can close.
        try:
            log_handle.close()
        except OSError:
            pass

    # Brief settle — detect instant crash.
    time.sleep(0.4)
    if proc.poll() is not None:
        diags.append(
            error(
                f"process завершился сразу (exit={proc.returncode}); см. {log_path}",
                code="1CX006",
                source="services",
                suggestion=f"1c-dev services logs {tool_id}",
            )
        )
        return False, diags

    write_pid(tool_id, proc.pid)
    diags.append(
        info(
            f"process запущен (pid={proc.pid})",
            code="1CX000",
            source="services",
        )
    )
    return True, diags


def stop_process(tool_id: str, *, progress: ProgressCb = None) -> tuple[bool, list[Diagnostic]]:
    diags: list[Diagnostic] = []
    pid = alive_pid(tool_id)
    if pid is None:
        clear_pid(tool_id)
        diags.append(info("process не запущен", code="1CX000", source="services"))
        return True, diags
    if progress:
        progress(f"Останавливаю pid={pid}…")
    ok = terminate(pid, timeout=10.0)
    clear_pid(tool_id)
    if not ok:
        diags.append(
            warning(
                f"не удалось подтвердить остановку pid={pid}",
                code="1CX006",
                source="services",
            )
        )
        return False, diags
    diags.append(info("process остановлен", code="1CX000", source="services"))
    return True, diags


def read_process_logs(tool_id: str, *, tail: int = 100) -> str:
    path = log_file(tool_id)
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    if tail > 0 and len(lines) > tail:
        lines = lines[-tail:]
    return "\n".join(lines) + ("\n" if lines else "")


def port_from_argv_or_url(argv: Sequence[str], url: str | None) -> int | None:
    """Extract --server.port=N or port from health/mcp URL."""
    for arg in argv:
        match = re.search(r"--server\.port=(\d+)", arg)
        if match:
            return int(match.group(1))
        if arg.startswith("--server.port"):
            continue
    if url:
        match = re.search(r":(\d+)(?:/|$)", url)
        if match:
            return int(match.group(1))
    return None
