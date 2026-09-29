"""Remove a configuration from the manifest (#100)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from core.configuration.get import CODE_CONF_UNKNOWN
from core.diagnostics import error
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import project_home, scope_root_from_manifest
from core.project.result import ProjectResult
from core.project.validate import validate_project

CODE_CONFIRM_REQUIRED = "1CC004"


def remove_configuration(
    start: Path | None = None,
    *,
    config_id: str,
    yes: bool = False,
    wipe_source: bool = False,
    wipe_runtime: bool = False,
) -> ProjectResult:
    """
    Remove configuration ``config_id`` from the manifest.

    Requires ``yes=True``. Optionally wipe source and/or linked runtime dirs.
    """
    if not yes:
        return ProjectResult(
            status="error",
            root=(start or Path.cwd()).resolve(),
            diagnostics=[
                error(
                    "Нужен флаг --yes для удаления configuration",
                    code=CODE_CONFIRM_REQUIRED,
                    suggestion="1c-dev configuration remove --id <id> --yes",
                )
            ],
        )

    start_path = (start or Path.cwd()).resolve()
    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return ProjectResult(
            status="error",
            root=start_path,
            diagnostics=[
                error(
                    "Манифест проекта не найден",
                    code="1CP001",
                    suggestion="Выполните 1c-dev init",
                )
            ],
        )

    root = scope_root_from_manifest(manifest_path)
    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=list(load_diags)
            or [error("Не удалось прочитать манифест", code="1CP002")],
        )

    configurations = data.get("configurations")
    if not isinstance(configurations, list):
        configurations = []
        data["configurations"] = configurations

    selected: dict[str, Any] | None = None
    remaining: list[Any] = []
    for conf in configurations:
        if isinstance(conf, dict) and conf.get("id") == config_id:
            selected = conf
        else:
            remaining.append(conf)

    if selected is None:
        known = [
            c.get("id")
            for c in configurations
            if isinstance(c, dict) and isinstance(c.get("id"), str)
        ]
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=[
                error(
                    f"Неизвестная configuration id={config_id!r}",
                    code=CODE_CONF_UNKNOWN,
                    suggestion=f"Доступные id: {', '.join(str(k) for k in known) or '(нет)'}",
                )
            ],
        )

    data["configurations"] = remaining
    was_default = selected.get("default") is True

    runtimes = data.get("runtimes")
    removed_runtimes: list[dict[str, Any]] = []
    kept_runtimes: list[Any] = []
    if isinstance(runtimes, list):
        for rt in runtimes:
            if isinstance(rt, dict) and rt.get("configuration") == config_id:
                removed_runtimes.append(rt)
            else:
                kept_runtimes.append(rt)
        data["runtimes"] = kept_runtimes
    else:
        data["runtimes"] = []

    # If we removed the default configuration, promote the first remaining one.
    if was_default and remaining:
        first = remaining[0]
        if isinstance(first, dict):
            first["default"] = True

    # Ensure exactly one default runtime when runtimes remain.
    kept = data["runtimes"]
    if isinstance(kept, list) and kept:
        has_default = any(
            isinstance(rt, dict) and rt.get("default") is True for rt in kept
        )
        if not has_default:
            for rt in kept:
                if isinstance(rt, dict):
                    rt["default"] = True
                    break

    # Drop / retarget publish profiles that pointed at removed runtimes.
    removed_rt_ids = {
        rt.get("id")
        for rt in removed_runtimes
        if isinstance(rt.get("id"), str)
    }
    publish = data.get("publish")
    if isinstance(publish, dict) and removed_rt_ids:
        profiles = publish.get("profiles")
        if isinstance(profiles, dict):
            surviving_rt_ids = {
                rt.get("id")
                for rt in (kept if isinstance(kept, list) else [])
                if isinstance(rt, dict) and isinstance(rt.get("id"), str)
            }
            new_profiles: dict[str, Any] = {}
            for pid, profile in profiles.items():
                if not isinstance(profile, dict):
                    continue
                rt_ref = profile.get("runtime")
                if isinstance(rt_ref, str) and rt_ref in removed_rt_ids:
                    if surviving_rt_ids:
                        # Retarget to first surviving runtime.
                        profile = dict(profile)
                        profile["runtime"] = next(iter(surviving_rt_ids))
                        new_profiles[pid] = profile
                    # else drop profile
                else:
                    new_profiles[pid] = profile
            publish["profiles"] = new_profiles
            default_profile = publish.get("default")
            if (
                isinstance(default_profile, str)
                and default_profile
                and default_profile not in new_profiles
            ):
                if new_profiles:
                    publish["default"] = next(iter(new_profiles))
                else:
                    data.pop("publish", None)
            elif not new_profiles:
                data.pop("publish", None)

    removed: list[str] = []
    if wipe_source:
        source = selected.get("source")
        if isinstance(source, dict):
            rel = source.get("path")
            if isinstance(rel, str) and rel:
                src_dir = (root / rel).resolve()
                try:
                    src_dir.relative_to(root)
                except ValueError:
                    pass
                else:
                    if src_dir.is_dir() and src_dir != root:
                        shutil.rmtree(src_dir)
                        removed.append(rel)

    if wipe_runtime:
        for rt in removed_runtimes:
            rel = rt.get("path")
            if isinstance(rel, str) and rel:
                rt_dir = (root / rel).resolve()
                try:
                    rt_dir.relative_to(root)
                except ValueError:
                    continue
                if rt_dir.is_dir() and rt_dir != root:
                    shutil.rmtree(rt_dir)
                    removed.append(rel)

    try:
        manifest_path.write_text(
            yaml.safe_dump(
                data,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ),
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            diagnostics=[
                error(f"Не удалось записать манифест: {exc}", code="1CP006")
            ],
        )

    result = validate_project(root)
    result.updated = [str(manifest_path.relative_to(root))]
    result.created = []  # unused
    if removed:
        result.skipped = []  # keep field clean
        # Surface wiped paths via updated-style list in created for CLI text.
        result.created = [f"removed:{p}" for p in removed]
    return result
