"""List extensions installed in the file IB (ADR-023 / #88)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_ibcmd import ExtensionInfo, IbcmdError, RunFn, list_extensions
from adapters.platform_ibcmd.constants import (
    CODE_IBCMD_MISSING,
    CODE_PROJECT,
    IB_MARKER,
    IBCMD_DATA_REL,
)
from core.diagnostics import Diagnostic, error
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import scope_root_from_manifest
from core.project.resolve import resolve_config_runtime

Status = Literal["ok", "error"]

CODE_IB_MISSING = "1CE010"


@dataclass
class ExtensionListResult:
    """Structured result for extension.list."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    root: Path | None = None
    runtime_path: Path | None = None
    extensions: list[ExtensionInfo] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.root is not None:
            payload["root"] = str(self.root)
        if self.runtime_path is not None:
            try:
                if self.root is not None:
                    payload["runtimePath"] = self.runtime_path.relative_to(
                        self.root
                    ).as_posix()
                else:
                    payload["runtimePath"] = str(self.runtime_path)
            except ValueError:
                payload["runtimePath"] = str(self.runtime_path)
        payload["extensions"] = [
            {"name": e.name, **({"raw": e.raw} if e.raw else {})}
            for e in self.extensions
        ]
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload


def run_extension_list(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    run: RunFn | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
) -> ExtensionListResult:
    """List extensions in the selected/default file IB via ibcmd."""
    start_path = (start or Path.cwd()).resolve()
    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return ExtensionListResult(
            status="error",
            diagnostics=[
                error(
                    "Файл 1c.project.yaml не найден",
                    code=CODE_PROJECT,
                    source="runtime",
                    suggestion="Выполните 1c-dev init --type configuration",
                )
            ],
        )

    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return ExtensionListResult(
            status="error",
            root=scope_root_from_manifest(manifest_path),
            diagnostics=list(load_diags)
            or [
                error(
                    "Не удалось прочитать манифест",
                    code=CODE_PROJECT,
                    source="runtime",
                )
            ],
        )

    root = scope_root_from_manifest(manifest_path)
    target, resolve_diags = resolve_config_runtime(
        data,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=True,
    )
    if target is None or target.runtime_rel is None:
        return ExtensionListResult(
            status="error",
            root=root,
            diagnostics=list(resolve_diags)
            or [
                error(
                    "Не удалось разрешить --config/--runtime",
                    code=CODE_PROJECT,
                    source="runtime",
                )
            ],
        )

    db_path = (root / target.runtime_rel).resolve()
    data_path = (root / IBCMD_DATA_REL).resolve()

    if not (db_path / IB_MARKER).is_file():
        return ExtensionListResult(
            status="error",
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    f"Информационная база не найдена: {target.runtime_rel}",
                    code=CODE_IB_MISSING,
                    source="runtime",
                    suggestion="Выполните 1c-dev build",
                )
            ],
        )

    discovery = (discover or discover_environment)()
    ibcmd_info = discovery.ibcmd
    if not ibcmd_info.found or ibcmd_info.path is None:
        return ExtensionListResult(
            status="error",
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    "ibcmd не найден",
                    code=CODE_IBCMD_MISSING,
                    source="platform",
                    suggestion=(
                        "Установите платформу 1С и добавьте ibcmd в PATH "
                        "(или в стандартный каталог установки)."
                    ),
                )
            ],
        )

    try:
        _result, items = list_extensions(
            ibcmd_info.path,
            db_path=db_path,
            data_path=data_path,
            run=run,
        )
    except IbcmdError as exc:
        return ExtensionListResult(
            status="error",
            root=root,
            runtime_path=db_path,
            diagnostics=list(exc.diagnostics)
            or [
                error(exc.message, code=exc.code, source="platform"),
            ],
        )

    return ExtensionListResult(
        status="ok",
        root=root,
        runtime_path=db_path,
        extensions=list(items),
    )
