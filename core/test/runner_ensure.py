"""Ensure YAXUNIT runner extension in the file IB from user cache (ADR-029 §7a).

Idempotent preflight before ``RunUnitTests``:

1. load ``YAxUnit.cfe`` (user cache / ``ONEC_YAXUNIT_CFE``) as extension ``YAXUNIT``;
2. switch off safe-mode / unsafe-action-protection for ``YAXUNIT`` and every
   ``purpose: tests`` extension of the selected configuration.

It never edits ``project.yaml`` or ``src/`` and is not a replacement for ``build``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_ibcmd import (
    ExtensionInfo,
    IbcmdError,
    RunFn,
    infobase_exists,
    list_extensions,
    load_cf_with_ibcmd,
    update_extension_properties,
)
from adapters.platform_ibcmd.constants import IBCMD_DATA_REL
from adapters.test_yaxunit import RUNNER_EXTENSION_NAME
from core.diagnostics import Diagnostic, error, warning
from core.test.constants import (
    CODE_IB_MISSING,
    CODE_IBCMD_MISSING,
    CODE_RUNNER_CFE_MISSING,
    CODE_RUNNER_ENSURE_FAILED,
    CODE_TEST_EXT_MISSING,
    RUNNER_STATE_NAME,
    RUNNER_YAXUNIT,
)
from core.test.store import test_home
from core.test.suites import SuiteRef
from core.toolchain.fetchers import sha256_file
from core.toolchain.resolve import YaxunitResolve, resolve_yaxunit_cfe

EnsureStatus = Literal["ok", "skipped", "failed"]
DiscoverFn = Callable[[], DiscoveryResult]
ResolveCfeFn = Callable[[], YaxunitResolve]

_OFF = "no"
_PROPS = ("safe-mode", "unsafe-action-protection")


@dataclass
class RunnerEnsureResult:
    """Outcome of the runner-extension preflight (``runnerEnsure`` in JSON)."""

    status: EnsureStatus
    steps: list[str] = field(default_factory=list)
    cfe_path: Path | None = None
    pin: str | None = None
    sha256: str | None = None
    loaded: bool = False
    safe_mode_off: list[str] = field(default_factory=list)
    reason: str | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.reason:
            payload["reason"] = self.reason
        if self.cfe_path is not None:
            payload["cfePath"] = str(self.cfe_path)
        if self.pin:
            payload["pin"] = self.pin
        if self.sha256:
            payload["sha256"] = self.sha256
        payload["loaded"] = self.loaded
        payload["steps"] = list(self.steps)
        if self.safe_mode_off:
            payload["safeModeOff"] = list(self.safe_mode_off)
        return payload


def runner_state_path(root: Path) -> Path:
    return test_home(root) / RUNNER_STATE_NAME


def _read_state(root: Path) -> dict[str, Any]:
    path = runner_state_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(root: Path, *, sha256: str, pin: str, cfe: Path, db_path: Path) -> None:
    path = runner_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"sha256": sha256, "pin": pin, "cfe": str(cfe), "ib": str(db_path)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def purpose_tests_extension_names(configuration: dict[str, Any]) -> list[str]:
    """Platform names of ``extensions[]`` with ``purpose: tests`` (declared order)."""
    raw = configuration.get("extensions")
    names: list[str] = []
    if not isinstance(raw, list):
        return names
    for item in raw:
        if not isinstance(item, dict) or item.get("purpose") != "tests":
            continue
        name = item.get("name") or item.get("id")
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return names


def _find(items: Sequence[ExtensionInfo], name: str) -> ExtensionInfo | None:
    for item in items:
        if item.name.lower() == name.lower():
            return item
    return None


def _needs_safe_mode_off(item: ExtensionInfo) -> bool:
    """True unless every safety property is known to be ``no`` already."""
    return any(item.prop(key) != _OFF for key in _PROPS)


def _failed(
    result: RunnerEnsureResult, diag: Diagnostic, *extra: Diagnostic
) -> RunnerEnsureResult:
    result.status = "failed"
    result.diagnostics.append(diag)
    result.diagnostics.extend(extra)
    return result


def _ibcmd_failure(result: RunnerEnsureResult, exc: IbcmdError, step: str) -> RunnerEnsureResult:
    return _failed(
        result,
        error(
            f"Не удалось подготовить runner YAXUNIT ({step}): {exc.message}",
            code=CODE_RUNNER_ENSURE_FAILED,
            source="test",
            suggestion="Проверьте ИБ (1c-dev build) и повторите; --no-runner-ensure пропускает шаг",
        ),
        *exc.diagnostics,
    )


def ensure_yaxunit_runner(
    *,
    root: Path,
    configuration: dict[str, Any],
    db_path: Path,
    suites: Sequence[SuiteRef] | None = None,
    discover: DiscoverFn | None = None,
    resolve_cfe: ResolveCfeFn | None = None,
    run: RunFn | None = None,
) -> RunnerEnsureResult:
    """
    Make sure ``YAXUNIT`` is installed in the IB and test extensions are not in safe-mode.

    ``suites=None`` — explicit ``yaxunit ensure`` (unconditional); otherwise the step is a
    no-op unless a selected suite uses ``runner: yaxunit``.
    """
    result = RunnerEnsureResult(status="ok")

    if suites is not None and not any(s.runner == RUNNER_YAXUNIT for s in suites):
        result.status = "skipped"
        result.reason = "нет suite с runner: yaxunit"
        return result

    if not infobase_exists(db_path):
        return _failed(
            result,
            error(
                f"File IB не найдена: {db_path}",
                code=CODE_IB_MISSING,
                source="test",
                suggestion="Сначала выполните 1c-dev build (ensure не собирает ИБ)",
            ),
        )

    discovery = (discover or discover_environment)()
    ibcmd = discovery.ibcmd
    if not ibcmd.found or ibcmd.path is None:
        return _failed(
            result,
            error(
                "ibcmd не найден",
                code=CODE_IBCMD_MISSING,
                source="platform",
                suggestion=(
                    "Установите платформу 1С и добавьте ibcmd в PATH "
                    "(или в стандартный каталог установки)."
                ),
            ),
        )

    resolved = (resolve_cfe or resolve_yaxunit_cfe)()
    if not resolved.found or resolved.path is None:
        return _failed(
            result,
            error(
                "YAxUnit.cfe не найден в user cache",
                code=CODE_RUNNER_CFE_MISSING,
                source="test",
                suggestion=(
                    f"Выполните 1c-dev tools sync или задайте {resolved.env_name}="
                    "/path/to/YAxUnit.cfe"
                ),
            ),
        )

    cfe = resolved.path
    result.cfe_path = cfe
    result.pin = resolved.pin or None
    data_path = (root / IBCMD_DATA_REL).resolve()
    ib = db_path.resolve()

    try:
        digest = sha256_file(cfe)
    except OSError as exc:
        return _failed(
            result,
            error(
                f"Не удалось прочитать {cfe}: {exc}",
                code=CODE_RUNNER_CFE_MISSING,
                source="test",
                suggestion="Проверьте файл или выполните 1c-dev tools sync",
            ),
        )
    result.sha256 = digest

    try:
        _, installed = list_extensions(ibcmd.path, db_path=ib, data_path=data_path, run=run)
    except IbcmdError as exc:
        return _ibcmd_failure(result, exc, "extension list")

    declared = {n.lower() for n in purpose_tests_extension_names(configuration)}
    runner_declared = RUNNER_EXTENSION_NAME.lower() in declared
    runner = _find(installed, RUNNER_EXTENSION_NAME)

    state = _read_state(root)
    version_matches = (
        runner is not None and bool(result.pin) and runner.prop("version") == result.pin
    )
    up_to_date = runner is not None and (
        state.get("sha256") == digest or (not state and version_matches)
    )

    if runner_declared:
        # Legacy / spike: project ships YAXUNIT itself — never overwrite it.
        result.reason = "YAXUNIT объявлен в project.yaml — загрузка пропущена"
    elif not up_to_date:
        try:
            result.steps.extend(
                load_cf_with_ibcmd(
                    ibcmd.path,
                    db_path=ib,
                    data_path=data_path,
                    cf_path=cfe,
                    extension=RUNNER_EXTENSION_NAME,
                    run=run,
                )
            )
        except IbcmdError as exc:
            return _ibcmd_failure(result, exc, "load YAXUNIT")
        result.loaded = True
        try:
            _, installed = list_extensions(ibcmd.path, db_path=ib, data_path=data_path, run=run)
        except IbcmdError as exc:
            return _ibcmd_failure(result, exc, "extension list")
    else:
        result.reason = "YAXUNIT уже загружен"

    wanted = [RUNNER_EXTENSION_NAME]
    wanted.extend(n for n in purpose_tests_extension_names(configuration) if n.lower() != "yaxunit")
    for name in wanted:
        item = _find(installed, name)
        if item is None:
            result.diagnostics.append(
                warning(
                    f"Extension {name} не найдено в ИБ — safe-mode не изменён",
                    code=CODE_TEST_EXT_MISSING,
                    source="test",
                    suggestion="Выполните 1c-dev build (загружает test-extension)",
                )
            )
            continue
        if not _needs_safe_mode_off(item):
            continue
        try:
            update_extension_properties(
                ibcmd.path,
                db_path=ib,
                data_path=data_path,
                name=item.name,
                run=run,
            )
        except IbcmdError as exc:
            return _ibcmd_failure(result, exc, f"extension update {item.name}")
        result.steps.append(f"safe-mode:{item.name}")
        result.safe_mode_off.append(item.name)

    if not runner_declared:
        _write_state(root, sha256=digest, pin=result.pin or "", cfe=cfe, db_path=ib)
    return result
