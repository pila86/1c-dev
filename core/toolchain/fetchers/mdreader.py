"""Fetch / build md-reader jar into user tools cache."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from adapters.source.mdclasses.constants import MDREADER_PIN, MIN_JAVA_MAJOR
from adapters.source.xmlgen.resolve import resolve_java
from core.diagnostics import Diagnostic, error
from core.toolchain.fetchers import find_gradle, gradlew_cmd, install_jar_pair, pin_artifact_name
from core.toolchain.manifest import ComponentSpec


def md_reader_source_root() -> Path:
    """Resolve tools/md-reader sources (monorepo or wheel layout)."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "tools" / "md-reader",  # core/toolchain/fetchers → repo
        here.parents[4] / "tools" / "md-reader",
        Path.cwd() / "tools" / "md-reader",
    ]
    for candidate in candidates:
        if (candidate / "build.gradle").is_file():
            return candidate
    raise FileNotFoundError(
        "Исходники tools/md-reader не найдены (нужны в wheel или monorepo)"
    )


def fetch_md_reader(
    spec: ComponentSpec,
    tools_dir: Path,
    *,
    env: dict[str, str] | None = None,
) -> tuple[Path | None, list[Diagnostic]]:
    """Idempotently build md-reader into tools_dir."""
    diagnostics: list[Diagnostic] = []
    pin = spec.pin or MDREADER_PIN
    artifact = spec.artifact
    pinned = tools_dir / pin_artifact_name(artifact, pin)
    stable = tools_dir / artifact

    if pinned.is_file():
        tools_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pinned, stable)
        return stable.resolve(), diagnostics

    min_java = spec.min_java or MIN_JAVA_MAJOR
    java = resolve_java(env=env, min_major=min_java)
    if not java.found or java.path is None:
        diagnostics.append(
            error(
                f"Java {min_java}+ не найдена (нужна для md-reader / MDClasses)",
                code="1CT011",
                source="toolchain",
                suggestion="Установите JDK 21+ и задайте JAVA_HOME.",
            )
        )
        return None, diagnostics

    try:
        src = md_reader_source_root()
    except FileNotFoundError as exc:
        diagnostics.append(
            error(
                str(exc),
                code="1CT012",
                source="toolchain",
                suggestion="Переустановите 1c-dev из git/wheel с tools/md-reader.",
            )
        )
        return None, diagnostics

    gradle_argv: list[str] | None = gradlew_cmd(src)
    if gradle_argv is None:
        gradle_bin = find_gradle()
        if gradle_bin:
            gradle_argv = [gradle_bin]
    if gradle_argv is None:
        diagnostics.append(
            error(
                "Gradle не найден (нужен Gradle 8+ или gradlew в tools/md-reader)",
                code="1CT013",
                source="toolchain",
                suggestion="Установите Gradle 8+ и добавьте в PATH.",
            )
        )
        return None, diagnostics

    run_env = dict(os.environ if env is None else env)
    run_env["JAVA_HOME"] = str(java.path.parent.parent)

    build = subprocess.run(
        [*gradle_argv, "fatJar", "--no-daemon", "-q"],
        cwd=str(src),
        capture_output=True,
        text=True,
        check=False,
        env=run_env,
    )
    if build.returncode != 0:
        diagnostics.append(
            error(
                "Сборка md-reader через Gradle завершилась с ошибкой",
                code="1CT014",
                source="toolchain",
                suggestion=(build.stderr or build.stdout or "").strip()[:500],
            )
        )
        return None, diagnostics

    built = src / "build" / "libs" / "md-reader.jar"
    if not built.is_file():
        diagnostics.append(
            error(
                f"Собранный md-reader jar не найден: {built}",
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
