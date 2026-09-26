"""Fetch / build docs-facade jar into user tools cache (ADR-017 / #51)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from adapters.source.xmlgen.resolve import resolve_java
from core.diagnostics import Diagnostic, error
from core.toolchain.fetchers import gradlew_cmd, install_jar_pair, pin_artifact_name, run_cmd
from core.toolchain.manifest import ComponentSpec
from core.toolchain.progress import ProgressFn, noop_progress

DOCS_FACADE_PIN = "bsl-context-0.10.0"
MIN_JAVA_MAJOR = 21


def docs_facade_source_root() -> Path:
    """Resolve tools/docs-facade sources (monorepo or wheel layout)."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "tools" / "docs-facade",  # core/toolchain/fetchers → repo
        here.parents[4] / "tools" / "docs-facade",
        Path.cwd() / "tools" / "docs-facade",
    ]
    for candidate in candidates:
        if (candidate / "build.gradle").is_file():
            return candidate
    raise FileNotFoundError(
        "Исходники tools/docs-facade не найдены (нужны в wheel или monorepo)"
    )


def fetch_docs_facade(
    spec: ComponentSpec,
    tools_dir: Path,
    *,
    env: dict[str, str] | None = None,
    progress: ProgressFn | None = None,
    quiet: bool = True,
) -> tuple[Path | None, list[Diagnostic]]:
    """Idempotently build docs-facade into tools_dir."""
    report = progress or noop_progress
    diagnostics: list[Diagnostic] = []
    pin = spec.pin or DOCS_FACADE_PIN
    artifact = spec.artifact
    pinned = tools_dir / pin_artifact_name(artifact, pin)
    stable = tools_dir / artifact

    if pinned.is_file():
        tools_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pinned, stable)
        report(f"→ {spec.id}: cache hit")
        return stable.resolve(), diagnostics

    min_java = spec.min_java or MIN_JAVA_MAJOR
    java = resolve_java(env=env, min_major=min_java)
    if not java.found or java.path is None:
        diagnostics.append(
            error(
                f"Java {min_java}+ не найдена (нужна для docs-facade / bsl-context)",
                code="1CT011",
                source="toolchain",
                suggestion="Установите JDK 21+ и задайте JAVA_HOME.",
            )
        )
        return None, diagnostics

    try:
        src = docs_facade_source_root()
    except FileNotFoundError as exc:
        diagnostics.append(
            error(
                str(exc),
                code="1CT012",
                source="toolchain",
                suggestion="Переустановите 1c-dev из git/wheel с tools/docs-facade.",
            )
        )
        return None, diagnostics

    gradle_argv = gradlew_cmd(src)
    if gradle_argv is None:
        diagnostics.append(
            error(
                "gradlew не найден в tools/docs-facade (нужен Gradle Wrapper)",
                code="1CT013",
                source="toolchain",
                suggestion=(
                    "Переустановите 1c-dev из git/wheel с полным tools/docs-facade (gradlew)."
                ),
            )
        )
        return None, diagnostics

    run_env = dict(os.environ if env is None else env)
    run_env["JAVA_HOME"] = str(java.path.parent.parent)

    report(f"→ {spec.id}: gradle fatJar…")
    cmd = [*gradle_argv, "fatJar", "--no-daemon"]
    if quiet:
        cmd.append("-q")
    build = run_cmd(cmd, cwd=str(src), env=run_env, quiet=quiet)
    if build.returncode != 0:
        diagnostics.append(
            error(
                "Сборка docs-facade через Gradle завершилась с ошибкой",
                code="1CT014",
                source="toolchain",
                suggestion=(build.stderr or build.stdout or "").strip()[:500]
                or "См. вывод Gradle выше.",
            )
        )
        return None, diagnostics

    built = src / "build" / "libs" / "docs-facade.jar"
    if not built.is_file():
        diagnostics.append(
            error(
                f"Собранный docs-facade jar не найден: {built}",
                code="1CT014",
                source="toolchain",
            )
        )
        return None, diagnostics

    stable_path = install_jar_pair(
        built=built,
        tools_dir=tools_dir,
        artifact=artifact,
        pin=pin,
    )
    return stable_path, diagnostics
