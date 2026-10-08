"""Designer ``/CheckModules`` via ``1cv8`` batch (ADR-030)."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from adapters.platform_ibcmd.constants import CODE_CHECK_FAILED
from core.diagnostics import Diagnostic
from core.diagnostics import error as diag_error

DEFAULT_MODES: tuple[str, ...] = ("Server",)
DEFAULT_TIMEOUT_SEC = 600.0

# {ОбщийМодуль.BrokenServer.Модуль(2,8)}: message
# {CommonModule.BrokenServer.Module(2,8)}: message
_OUT_LOC = re.compile(
    r"^\{"
    r"(?P<type>[^.{}]+)\."
    r"(?P<name>[^.{}]+)\."
    r"(?P<module>[^.{}(]+)"
    r"\((?P<line>\d+),(?P<column>\d+)\)"
    r"\}:\s*(?P<message>.*)$"
)

_TYPE_MAP = {
    "ОбщийМодуль": "CommonModule",
    "CommonModule": "CommonModule",
    "Справочник": "Catalog",
    "Catalog": "Catalog",
    "Документ": "Document",
    "Document": "Document",
    "Обработка": "DataProcessor",
    "DataProcessor": "DataProcessor",
    "Отчет": "Report",
    "Report": "Report",
    "HTTPСервис": "HTTPService",
    "HTTPService": "HTTPService",
    "WebСервис": "WebService",
    "WebService": "WebService",
}

_MODULE_MAP = {
    "Модуль": "Module",
    "Module": "Module",
    "МодульОбъекта": "ObjectModule",
    "ObjectModule": "ObjectModule",
    "МодульМенеджера": "ManagerModule",
    "ManagerModule": "ManagerModule",
    "МодульФормы": "FormModule",
    "FormModule": "FormModule",
}

_SUCCESS_MARKERS = (
    "Синтаксических ошибок не обнаружено",
    "No syntax errors detected",
)


class CheckModulesError(Exception):
    """Designer /CheckModules failure with structured diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_CHECK_FAILED,
        diagnostics: list[Diagnostic] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.diagnostics = diagnostics or [
            diag_error(message, code=code, source="platform")
        ]


@dataclass(frozen=True)
class ProcessRunResult:
    """Raw result of one ``1cv8 DESIGNER`` invocation."""

    returncode: int
    argv: list[str]
    timed_out: bool = False


RunFn = Callable[[list[str], float], ProcessRunResult]


def normalize_modes(modes: Sequence[str] | None) -> list[str]:
    """Return non-empty unique mode names (Designer flag without leading ``-``)."""
    if not modes:
        return list(DEFAULT_MODES)
    seen: set[str] = set()
    out: list[str] = []
    for raw in modes:
        name = raw.strip().lstrip("-")
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    if not out:
        raise CheckModulesError(
            "не указан ни один режим /CheckModules",
            code=CODE_CHECK_FAILED,
            diagnostics=[
                diag_error(
                    "не указан ни один режим /CheckModules "
                    "(нужен хотя бы Server)",
                    code=CODE_CHECK_FAILED,
                    source="platform",
                    suggestion="передайте --mode Server",
                )
            ],
        )
    return out


def build_check_modules_argv(
    onecv8: Path,
    *,
    ib_path: Path,
    out_log: Path,
    modes: Sequence[str] | None = None,
) -> list[str]:
    """Build argv for ``1cv8 DESIGNER … /CheckModules -Mode…``."""
    mode_flags = [f"-{m}" for m in normalize_modes(modes)]
    return [
        str(onecv8),
        "DESIGNER",
        f"/F{ib_path.resolve()}",
        "/DisableStartupDialogs",
        "/DisableStartupMessages",
        "/Out",
        str(out_log.resolve()),
        "/CheckModules",
        *mode_flags,
    ]


def default_run(argv: list[str], timeout: float) -> ProcessRunResult:
    """Run process in a new session; on timeout kill the process group."""
    args = list(argv)
    if sys.platform == "win32":
        creationflags = 0x00000200  # CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
        try:
            returncode = proc.wait(timeout=timeout)
            return ProcessRunResult(returncode=returncode, argv=args, timed_out=False)
        except subprocess.TimeoutExpired:
            proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
            return ProcessRunResult(returncode=124, argv=args, timed_out=True)

    proc = subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
    try:
        returncode = proc.wait(timeout=timeout)
        return ProcessRunResult(returncode=returncode, argv=args, timed_out=False)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        return ProcessRunResult(returncode=124, argv=args, timed_out=True)


def parse_check_modules_out(text: str) -> list[Diagnostic]:
    """
    Parse Designer ``/Out`` from ``/CheckModules``.

    Location lines become diagnostics; success markers yield an empty list.
    """
    cleaned = text.lstrip("\ufeff")
    if any(marker in cleaned for marker in _SUCCESS_MARKERS):
        # Success message may still appear alone; ignore other noise.
        if not _OUT_LOC.search(cleaned):
            return []

    diagnostics: list[Diagnostic] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _OUT_LOC.match(line)
        if match is None:
            continue
        type_raw = match.group("type")
        name = match.group("name")
        module_raw = match.group("module")
        message = match.group("message").strip()
        # Strip trailing " (Проверка: Сервер)" noise if present — keep in message.
        ir_type = _TYPE_MAP.get(type_raw, type_raw)
        module = _MODULE_MAP.get(module_raw, module_raw)
        diag: Diagnostic = {
            "severity": "error",
            "code": CODE_CHECK_FAILED,
            "message": message,
            "object": f"{ir_type}.{name}",
            "module": module,
            "line": int(match.group("line")),
            "column": int(match.group("column")),
            "source": "platform",
        }
        diagnostics.append(diag)
    return diagnostics


def check_modules(
    onecv8: Path,
    *,
    ib_path: Path,
    out_log: Path,
    modes: Sequence[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    run: RunFn | None = None,
) -> None:
    """
    Run Designer ``/CheckModules`` on an existing file IB.

    Raises ``CheckModulesError`` on timeout, non-zero exit, or parsed errors.
    """
    out_log.parent.mkdir(parents=True, exist_ok=True)
    if out_log.exists():
        out_log.unlink()

    argv = build_check_modules_argv(
        onecv8,
        ib_path=ib_path,
        out_log=out_log,
        modes=modes,
    )
    runner = run or default_run
    result = runner(argv, timeout)

    out_text = ""
    if out_log.is_file():
        out_text = out_log.read_text(encoding="utf-8-sig", errors="replace")

    if result.timed_out:
        raise CheckModulesError(
            f"таймаут /CheckModules ({timeout:g}s)",
            code=CODE_CHECK_FAILED,
            diagnostics=[
                diag_error(
                    f"таймаут /CheckModules ({timeout:g}s)",
                    code=CODE_CHECK_FAILED,
                    source="platform",
                )
            ],
        )

    parsed = parse_check_modules_out(out_text)
    if result.returncode == 0 and not parsed:
        return

    if parsed:
        raise CheckModulesError(
            "синтаксические ошибки модулей",
            code=CODE_CHECK_FAILED,
            diagnostics=parsed,
        )

    detail = out_text.strip() or f"код возврата {result.returncode}"
    if len(detail) > 800:
        detail = detail[:800] + "…"
    raise CheckModulesError(
        f"/CheckModules завершился с ошибкой: {detail}",
        code=CODE_CHECK_FAILED,
        diagnostics=[
            diag_error(
                f"/CheckModules завершился с ошибкой: {detail}",
                code=CODE_CHECK_FAILED,
                source="platform",
            )
        ],
    )
