"""Resolve toolchain jars from env override or user cache (ADR-013 / #49)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.toolchain.cache import tools_cache_dir
from core.toolchain.fetchers import pin_artifact_name
from core.toolchain.manifest import ComponentSpec, ToolchainManifest, load_manifest

JarSource = Literal["env", "cache"]


@dataclass(frozen=True)
class JarResolve:
    """Resolved toolchain jar path and origin."""

    found: bool
    path: Path | None = None
    source: JarSource | None = None
    deferred: bool = False


def resolve_component_jar(
    spec: ComponentSpec,
    *,
    env: dict[str, str] | None = None,
    cache_env: dict[str, str] | None = None,
) -> JarResolve:
    """Find a component jar: env override → stable cache → pinned cache."""
    environ = env if env is not None else os.environ
    tools_dir = tools_cache_dir(env=cache_env if cache_env is not None else env)

    if spec.env:
        override = environ.get(spec.env, "").strip()
        if override:
            path = Path(override).expanduser()
            if path.is_file():
                return JarResolve(found=True, path=path.resolve(), source="env")
            return JarResolve(
                found=False,
                path=path,
                source="env",
                deferred=spec.deferred,
            )

    stable = tools_dir / spec.artifact
    if stable.is_file():
        return JarResolve(found=True, path=stable.resolve(), source="cache")

    pin = (spec.pin or "").strip()
    if pin and pin.lower() != "deferred":
        pinned = tools_dir / pin_artifact_name(spec.artifact, pin)
        if pinned.is_file():
            return JarResolve(found=True, path=pinned.resolve(), source="cache")

    return JarResolve(
        found=False,
        path=stable,
        deferred=spec.deferred,
    )


def resolve_manifest_jars(
    *,
    manifest: ToolchainManifest | None = None,
    env: dict[str, str] | None = None,
    cache_env: dict[str, str] | None = None,
) -> dict[str, JarResolve]:
    """Resolve every component in the toolchain manifest."""
    loaded = manifest if manifest is not None else load_manifest()
    return {
        spec.id: resolve_component_jar(spec, env=env, cache_env=cache_env)
        for spec in loaded.components
    }


def sync_suggestion() -> str:
    """Primary hint to bootstrap missing jars."""
    return "1c-dev doctor --fix  # или: 1c-dev tools sync"
