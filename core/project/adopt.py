"""Apply discovered sources into an empty project manifest (ADR-034)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.configuration.register import register_configuration_entry, write_manifest_yaml
from core.diagnostics import Diagnostic
from core.project.discover_sources import DiscoverSourcesResult, discover_sources
from core.project.load import load_manifest
from core.project.paths import home_manifest_path
from core.project.source_paths import store_source_path
from core.test.suites import ensure_unit_suite


@dataclass
class AdoptResult:
    """Result of adopting discovered sources into the manifest."""

    status: str  # "ok" | "skipped" | "error"
    adopted: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    created: list[str] = field(default_factory=list)


def _empty_adopted() -> dict[str, Any]:
    return {
        "configurations": [],
        "extensions": [],
        "tests": [],
    }


def apply_discovered_sources(
    root: Path,
    data: dict[str, Any],
    discovered: DiscoverSourcesResult,
) -> AdoptResult:
    """
    Mutate ``data`` in place: register configurations, extensions, tests, runtimes.

    Does not write the manifest file.
    """
    adopted = _empty_adopted()
    diagnostics = list(discovered.diagnostics)
    created: list[str] = []

    if not discovered.configurations:
        return AdoptResult(
            status="skipped",
            adopted=adopted,
            diagnostics=diagnostics,
        )

    conf_by_rel: dict[str, dict[str, Any]] = {}
    for conf_src in discovered.configurations:
        store_path = store_source_path(root, conf_src.path)
        reg = register_configuration_entry(
            data,
            root,
            config_id=conf_src.suggested_id,
            name=conf_src.name,
            source_path=store_path,
            format=conf_src.format,
            with_runtime=True,
            ensure_source_dir=False,
        )
        if reg.status != "ok":
            diagnostics.extend(reg.diagnostics)
            continue
        created.extend(reg.created)
        configurations = data.get("configurations")
        if not isinstance(configurations, list):
            continue
        conf_entry = next(
            (
                c
                for c in configurations
                if isinstance(c, dict) and c.get("id") == reg.config_id
            ),
            None,
        )
        if conf_entry is None:
            continue
        conf_by_rel[conf_src.rel_path] = conf_entry
        adopted["configurations"].append(
            {
                "id": reg.config_id,
                "format": conf_src.format,
                "path": store_path,
            }
        )

    # Attach extensions to parent configurations.
    test_ids_by_conf: dict[str, list[str]] = {}
    for ext in discovered.extensions:
        parent_rel = ext.parent_config_rel
        conf_entry = conf_by_rel.get(parent_rel) if parent_rel else None
        if conf_entry is None and conf_by_rel:
            # Fallback to first / default conf.
            conf_entry = next(iter(conf_by_rel.values()))
        if conf_entry is None:
            continue
        store_path = store_source_path(root, ext.path)
        purpose = ext.purpose or "product"
        exts = conf_entry.get("extensions")
        if not isinstance(exts, list):
            exts = []
            conf_entry["extensions"] = exts
        exts.append(
            {
                "id": ext.suggested_id,
                "name": ext.name,
                "purpose": purpose,
                "source": {"format": ext.format, "path": store_path},
            }
        )
        adopted["extensions"].append(
            {
                "id": ext.suggested_id,
                "purpose": purpose,
                "path": store_path,
                "configuration": conf_entry.get("id"),
            }
        )
        if purpose == "tests":
            conf_id = str(conf_entry.get("id") or "")
            test_ids_by_conf.setdefault(conf_id, []).append(ext.suggested_id)

    for conf_id, ext_ids in test_ids_by_conf.items():
        configurations = data.get("configurations")
        if not isinstance(configurations, list):
            continue
        for conf in configurations:
            if isinstance(conf, dict) and conf.get("id") == conf_id:
                ensure_unit_suite(conf, ext_ids)
                adopted["tests"].append(
                    {"id": "unit", "runner": "yaxunit", "extensions": list(ext_ids)}
                )
                break

    return AdoptResult(
        status="ok",
        adopted=adopted,
        diagnostics=diagnostics,
        created=created,
    )


def adopt_into_manifest(root: Path) -> AdoptResult:
    """
    Discover sources under ``root`` and write them into ``.1c-dev/project.yaml``.

    Expects an already-scaffolded empty (or existing) manifest.
    """
    manifest_path = home_manifest_path(root)
    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return AdoptResult(
            status="error",
            adopted=_empty_adopted(),
            diagnostics=list(load_diags),
        )

    discovered = discover_sources(root)
    result = apply_discovered_sources(root, data, discovered)
    if result.status == "ok":
        write_manifest_yaml(manifest_path, data)
    return result
