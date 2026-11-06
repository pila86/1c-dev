"""Subprocess wrappers for ``1cedtcli`` export (ADR-032 / #155)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from adapters.edtcli.constants import (
    CODE_EDTCLI_COLLISION,
    CODE_EDTCLI_EMPTY_EXPORT,
    CODE_EDTCLI_FAILED,
    CODE_EDTCLI_MISSING,
    CODE_EDTCLI_VERSION,
    DEFAULT_EXPORT_TIMEOUT_SEC,
    EDTCLI_MISSING_HINT,
    MIN_EDT_MAJOR,
    MIN_EDT_MINOR,
)
from adapters.edtcli.discovery import EdtCliInfo, discover_edtcli
from core.diagnostics import Diagnostic, error


class EdtCliError(Exception):
    """1cedtcli step failure with structured diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_EDTCLI_FAILED,
        diagnostics: list[Diagnostic] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.diagnostics = diagnostics or []


@dataclass(frozen=True)
class EdtCliRunResult:
    """Raw result of one 1cedtcli invocation."""

    returncode: int
    stdout: str
    stderr: str
    argv: list[str]


RunFn = Callable[[list[str]], EdtCliRunResult]


def version_tuple(version: str | None) -> tuple[int, ...] | None:
    """Parse ``2026.2.2+21`` → ``(2026, 2, 2, 21)``; ``None`` if unparsable."""
    if not version:
        return None
    base, _, build = version.partition("+")
    parts: list[int] = []
    for piece in base.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            return None
    if not parts:
        return None
    if build:
        try:
            parts.append(int(build))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def is_edt_version_supported(version: str | None) -> bool:
    """
    True if version is unknown (cannot decide) or ≥ 2025.1.

    Unknown versions are allowed: PATH installs may omit a version segment.
    """
    parsed = version_tuple(version)
    if parsed is None:
        return True
    major = parsed[0] if len(parsed) > 0 else 0
    minor = parsed[1] if len(parsed) > 1 else 0
    return (major, minor) >= (MIN_EDT_MAJOR, MIN_EDT_MINOR)


def require_edtcli(
    *,
    info: EdtCliInfo | None = None,
) -> EdtCliInfo:
    """Resolve ``1cedtcli`` or raise ``EdtCliError`` (1CS001 / 1CS002)."""
    resolved = info if info is not None else discover_edtcli()
    if not resolved.found or resolved.path is None:
        raise EdtCliError(
            "1cedtcli не найден",
            code=CODE_EDTCLI_MISSING,
            diagnostics=[
                error(
                    "1cedtcli не найден (нужен для build/check при source.format: edt)",
                    code=CODE_EDTCLI_MISSING,
                    source="edt",
                    suggestion=EDTCLI_MISSING_HINT,
                )
            ],
        )
    if not is_edt_version_supported(resolved.version):
        ver = resolved.version or "?"
        raise EdtCliError(
            f"1cedtcli {ver} ниже минимума {MIN_EDT_MAJOR}.{MIN_EDT_MINOR}",
            code=CODE_EDTCLI_VERSION,
            diagnostics=[
                error(
                    f"1cedtcli версии {ver}: нужен ≥{MIN_EDT_MAJOR}.{MIN_EDT_MINOR}",
                    code=CODE_EDTCLI_VERSION,
                    source="edt",
                    suggestion=EDTCLI_MISSING_HINT,
                )
            ],
        )
    return resolved


def default_run(
    argv: list[str],
    *,
    timeout: int = DEFAULT_EXPORT_TIMEOUT_SEC,
) -> EdtCliRunResult:
    """Execute 1cedtcli and capture output."""
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout + 60,
    )
    return EdtCliRunResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        argv=list(argv),
    )


def _combined_output(result: EdtCliRunResult) -> str:
    return f"{result.stdout}\n{result.stderr}".strip()


def _validate_export_dir(export_dir: Path) -> None:
    """Fail on empty / incomplete Designer XML export (1CS007)."""
    configuration_xml = export_dir / "Configuration.xml"
    if not configuration_xml.is_file() or configuration_xml.stat().st_size == 0:
        raise EdtCliError(
            f"Пустой export: нет непустого Configuration.xml в {export_dir}",
            code=CODE_EDTCLI_EMPTY_EXPORT,
            diagnostics=[
                error(
                    "1cedtcli export завершился без Configuration.xml "
                    "(пустой или битый XML staging)",
                    code=CODE_EDTCLI_EMPTY_EXPORT,
                    source="edt",
                    suggestion=(
                        "Проверьте EDT-проект (.project / Configuration.mdo) "
                        "и повторите build"
                    ),
                )
            ],
        )
    text = configuration_xml.read_text(encoding="utf-8-sig", errors="replace")
    # MetaDataObject dump always has a ChildObjects section (may be empty).
    if "ChildObjects" not in text:
        raise EdtCliError(
            f"Пустой export: Configuration.xml без ChildObjects в {export_dir}",
            code=CODE_EDTCLI_EMPTY_EXPORT,
            diagnostics=[
                error(
                    "1cedtcli export: Configuration.xml без ChildObjects",
                    code=CODE_EDTCLI_EMPTY_EXPORT,
                    source="edt",
                    suggestion="Проверьте состав EDT-проекта и повторите export",
                )
            ],
        )


def export_configuration(
    edtcli: Path,
    *,
    project: Path,
    configuration_files: Path,
    timeout: int = DEFAULT_EXPORT_TIMEOUT_SEC,
    workspace: Path | None = None,
    run: RunFn | None = None,
) -> EdtCliRunResult:
    """
    ``1cedtcli -data <fresh> -timeout N -command export --project … --configuration-files …``.

    Always uses a fresh ``-data`` workspace (tmpdir unless ``workspace`` is set).
    Premature EOF on stderr with exit 0 + non-empty Configuration.xml is OK (ADR-032).
    """
    project_abs = project.resolve()
    export_abs = configuration_files.resolve()
    export_abs.mkdir(parents=True, exist_ok=True)

    runner = run or (lambda argv: default_run(argv, timeout=timeout))

    def _invoke(ws: Path) -> EdtCliRunResult:
        argv = [
            str(edtcli),
            "-data",
            str(ws),
            "-timeout",
            str(timeout),
            "-command",
            "export",
            "--project",
            str(project_abs),
            "--configuration-files",
            str(export_abs),
        ]
        return runner(argv)

    if workspace is not None:
        workspace.mkdir(parents=True, exist_ok=True)
        result = _invoke(workspace.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="1c-dev-edt-ws-") as tmp:
            result = _invoke(Path(tmp))

    if result.returncode == 204:
        raise EdtCliError(
            "1cedtcli: проект уже есть в workspace (rc 204)",
            code=CODE_EDTCLI_COLLISION,
            diagnostics=[
                error(
                    "1cedtcli export: workspace collision (rc 204)",
                    code=CODE_EDTCLI_COLLISION,
                    source="edt",
                    suggestion=(
                        "Используйте свежий -data (tmpdir); не шарьте bake-off workspace"
                    ),
                )
            ],
        )

    if result.returncode != 0:
        detail = _combined_output(result)
        raise EdtCliError(
            f"1cedtcli export завершился с кодом {result.returncode}",
            code=CODE_EDTCLI_FAILED,
            diagnostics=[
                error(
                    f"1cedtcli export failed (rc={result.returncode})"
                    + (f": {detail[:500]}" if detail else ""),
                    code=CODE_EDTCLI_FAILED,
                    source="edt",
                    suggestion="Проверьте логи -data workspace и версию EDT ≥2025.1",
                )
            ],
        )

    _validate_export_dir(export_abs)
    return result


def prepare_export_dir(export_dir: Path) -> Path:
    """Recreate export staging directory (cache under ``.1c-dev/export/<id>/``)."""
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir.resolve()
