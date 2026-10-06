"""Static test-module discovery from extension sources (ADR-029 variant C)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.test.suites import ExtensionRef, SuiteRef, extension_source_dirs

# Процедура/Функция ИсполняемыеСценарии(...) Экспорт — YaXUnit entry point.
_EXECUTABLE_SCENARIOS = re.compile(
    r"(?im)^\s*(?:Процедура|Функция)\s+ИсполняемыеСценарии\s*\([^)]*\)\s*Экспорт\b"
)


def module_has_executable_scenarios(bsl_text: str) -> bool:
    """True if module exports ``ИсполняемыеСценарии``."""
    return _EXECUTABLE_SCENARIOS.search(bsl_text) is not None


def _iter_common_module_bsl(ext_root: Path) -> list[tuple[str, Path]]:
    """Return (module_name, Module.bsl path) under CommonModules."""
    common = ext_root / "CommonModules"
    if not common.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for child in sorted(common.iterdir()):
        if not child.is_dir():
            continue
        bsl = child / "Ext" / "Module.bsl"
        if bsl.is_file():
            found.append((child.name, bsl))
    return found


def discover_modules(
    root: Path,
    suites: list[SuiteRef],
) -> list[dict[str, Any]]:
    """
    Scan suite test-extension sources for modules with ``ИсполняемыеСценарии``.

    Level: suites / extensions / modules (not individual tests — ADR-029).
    """
    modules: list[dict[str, Any]] = []
    # Map extension id → suite ids that reference it
    suite_by_ext: dict[str, list[str]] = {}
    for suite in suites:
        for ext in suite.extensions:
            suite_by_ext.setdefault(ext.id, []).append(suite.id)

    for ext, ext_path in extension_source_dirs(root, suites):
        if not ext_path.is_dir():
            continue
        for module_name, bsl_path in _iter_common_module_bsl(ext_path):
            try:
                text = bsl_path.read_text(encoding="utf-8-sig")
            except OSError:
                continue
            if not module_has_executable_scenarios(text):
                continue
            try:
                rel = bsl_path.relative_to(root).as_posix()
            except ValueError:
                rel = str(bsl_path)
            modules.append(
                {
                    "name": module_name,
                    "extensionId": ext.id,
                    "extension": ext.name,
                    "suiteIds": list(suite_by_ext.get(ext.id, [])),
                    "path": rel,
                }
            )
    return modules


def discover_modules_for_extension(
    root: Path,
    ext: ExtensionRef,
) -> list[dict[str, Any]]:
    """Discover modules for a single extension (tests)."""
    if not ext.source_rel:
        return []
    ext_path = (root / ext.source_rel).resolve()
    if not ext_path.is_dir():
        return []
    modules: list[dict[str, Any]] = []
    for module_name, bsl_path in _iter_common_module_bsl(ext_path):
        try:
            text = bsl_path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        if not module_has_executable_scenarios(text):
            continue
        try:
            rel = bsl_path.relative_to(root).as_posix()
        except ValueError:
            rel = str(bsl_path)
        modules.append(
            {
                "name": module_name,
                "extensionId": ext.id,
                "extension": ext.name,
                "path": rel,
            }
        )
    return modules
