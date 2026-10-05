"""Resolve toolchain jars / apache home from env or user cache (ADR-013 / #49 / #94)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.toolchain.cache import tools_cache_dir
from core.toolchain.fetchers import pin_artifact_name
from core.toolchain.fetchers.apache import (
    STABLE_NAME as APACHE_STABLE,
)
from core.toolchain.fetchers.apache import (
    httpd_binary,
    is_bundled_apache_home,
    read_modules_dir,
)
from core.toolchain.manifest import ComponentSpec, ToolchainManifest, load_manifest

JarSource = Literal["env", "cache"]
ApacheSource = Literal["env", "cache"]
YAXUNIT_ID = "yaxunit"
YAXUNIT_ENV = "ONEC_YAXUNIT_CFE"


@dataclass(frozen=True)
class JarResolve:
    """Resolved toolchain jar path and origin."""

    found: bool
    path: Path | None = None
    source: JarSource | None = None
    deferred: bool = False


@dataclass(frozen=True)
class ApacheResolve:
    """Resolved user-owned Apache httpd home (ADR-025 / #94)."""

    found: bool
    home: Path | None = None
    httpd: Path | None = None
    modules_dir: Path | None = None
    source: ApacheSource | None = None


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
    """Resolve jar components in the toolchain manifest (skip directory homes)."""
    loaded = manifest if manifest is not None else load_manifest()
    return {
        spec.id: resolve_component_jar(spec, env=env, cache_env=cache_env)
        for spec in loaded.components
        if spec.artifact.endswith(".jar")
    }


def resolve_apache_home(
    *,
    env: dict[str, str] | None = None,
    cache_env: dict[str, str] | None = None,
    manifest: ToolchainManifest | None = None,
) -> ApacheResolve:
    """Find Apache home: ONEC_APACHE_HOME → tools/apache → tools/apache-<pin>."""
    environ = env if env is not None else os.environ
    tools_dir = tools_cache_dir(env=cache_env if cache_env is not None else env)
    loaded = manifest if manifest is not None else load_manifest()
    spec = loaded.get("apache")
    env_name = (spec.env if spec is not None else None) or "ONEC_APACHE_HOME"

    override = environ.get(env_name, "").strip()
    if override:
        home = Path(override).expanduser()
        httpd = httpd_binary(home)
        modules = read_modules_dir(home)
        if httpd is not None and modules is not None:
            return ApacheResolve(
                found=True,
                home=home.resolve(),
                httpd=httpd,
                modules_dir=modules,
                source="env",
            )
        return ApacheResolve(found=False, home=home, source="env")

    stable = tools_dir / APACHE_STABLE
    if is_bundled_apache_home(stable):
        httpd = httpd_binary(stable)
        return ApacheResolve(
            found=True,
            home=stable.resolve(),
            httpd=httpd,
            modules_dir=read_modules_dir(stable),
            source="cache",
        )

    pin = (spec.pin if spec is not None else "") or ""
    if pin.strip() and pin.strip().lower() != "deferred":
        pinned = tools_dir / f"{APACHE_STABLE}-{pin.strip()}"
        if is_bundled_apache_home(pinned):
            httpd = httpd_binary(pinned)
            return ApacheResolve(
                found=True,
                home=pinned.resolve(),
                httpd=httpd,
                modules_dir=read_modules_dir(pinned),
                source="cache",
            )

    return ApacheResolve(found=False, home=stable)


@dataclass(frozen=True)
class YaxunitResolve:
    """Resolved YAxUnit runner ``.cfe`` (ADR-029 §7a)."""

    found: bool
    path: Path | None = None
    source: JarSource | None = None
    pin: str = ""
    env_name: str = YAXUNIT_ENV


def resolve_yaxunit_cfe(
    *,
    env: dict[str, str] | None = None,
    cache_env: dict[str, str] | None = None,
    manifest: ToolchainManifest | None = None,
) -> YaxunitResolve:
    """Find YAxUnit.cfe: ``ONEC_YAXUNIT_CFE`` → tools/yaxunit.cfe → tools/yaxunit-<pin>.cfe."""
    loaded = manifest if manifest is not None else load_manifest()
    spec = loaded.get(YAXUNIT_ID)
    if spec is None:
        return YaxunitResolve(found=False)
    resolved = resolve_component_jar(spec, env=env, cache_env=cache_env)
    return YaxunitResolve(
        found=resolved.found,
        path=resolved.path,
        source=resolved.source,
        pin=spec.pin,
        env_name=spec.env or YAXUNIT_ENV,
    )


def sync_suggestion() -> str:
    """Primary hint to bootstrap missing jars."""
    return "1c-dev doctor --fix  # или: 1c-dev tools sync"
