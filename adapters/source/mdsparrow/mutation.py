"""Run md-sparrow apply-mutation (ADR-032 write path D / #153)."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.edtcli.constants import MD_SPARROW_JDK_HINT
from adapters.source.mdsparrow.constants import (
    DEFAULT_MUTATION_TIMEOUT_SEC,
    ENV_UNAVAILABLE_CODE,
    MIN_JAVA_MAJOR,
    MUTATION_FAILED_CODE,
)
from adapters.source.mdsparrow.resolve import (
    ToolResolve,
    fetch_script_suggestion,
    resolve_jar,
    resolve_java,
)


class MdSparrowError(Exception):
    """md-sparrow subprocess or environment failure."""

    def __init__(self, message: str, *, code: str = ENV_UNAVAILABLE_CODE) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ApplyMutationResult:
    """Outcome of a successful apply-mutation invocation."""

    stdout: str
    stderr: str


def apply_mutation(
    params: dict[str, Any] | Path,
    *,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
    cwd: Path | None = None,
    timeout: int = DEFAULT_MUTATION_TIMEOUT_SEC,
) -> ApplyMutationResult:
    """
    Invoke ``md-sparrow apply-mutation --params=<ascii-path.json>``.

    ``params`` is either a JSON-serializable dict (written to a temp UTF-8 file)
    or an existing params file path (must be ASCII-friendly for Windows JVM).

    ``timeout`` is the wall-clock budget in seconds (subprocess gets
    ``timeout + 60``, same slack as ``1cedtcli``).
    """
    jar_r = jar if jar is not None else resolve_jar()
    java_r = java if java is not None else resolve_java()
    if not java_r.found or java_r.path is None:
        raise MdSparrowError(
            f"Java {MIN_JAVA_MAJOR}+ не найдена (нужна для md-sparrow)",
            code=ENV_UNAVAILABLE_CODE,
        )
    if not jar_r.found or jar_r.path is None:
        raise MdSparrowError(
            f"md-sparrow jar не найден ({fetch_script_suggestion()}; "
            f"{MD_SPARROW_JDK_HINT})",
            code=ENV_UNAVAILABLE_CODE,
        )

    with tempfile.TemporaryDirectory(prefix="1c-dev-mdsparrow-") as tmp:
        if isinstance(params, Path):
            params_path = params.expanduser().resolve()
            if not params_path.is_file():
                raise MdSparrowError(
                    f"Файл параметров apply-mutation не найден: {params_path}",
                    code=MUTATION_FAILED_CODE,
                )
        else:
            params_path = Path(tmp) / "params.json"
            params_path.write_text(
                json.dumps(params, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        # Path must stay ASCII for Windows JVM argv (md-sparrow requirement).
        try:
            params_path.as_posix().encode("ascii")
        except UnicodeEncodeError as exc:
            raise MdSparrowError(
                "Путь к --params должен быть ASCII (требование md-sparrow)",
                code=MUTATION_FAILED_CODE,
            ) from exc

        cmd = [
            str(java_r.path),
            "-jar",
            str(jar_r.path),
            "apply-mutation",
            f"--params={params_path}",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=str(cwd) if cwd is not None else None,
                timeout=timeout + 60,
            )
        except subprocess.TimeoutExpired as exc:
            raise MdSparrowError(
                f"md-sparrow apply-mutation превысил timeout "
                f"({timeout + 60}s)",
                code=MUTATION_FAILED_CODE,
            ) from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            msg = "md-sparrow apply-mutation завершился с ошибкой"
            if detail:
                msg = f"{msg}: {detail[:500]}"
            raise MdSparrowError(msg, code=MUTATION_FAILED_CODE)

        return ApplyMutationResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
