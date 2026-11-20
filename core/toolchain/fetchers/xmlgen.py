"""Fetch / build xml-gen jar into user tools cache."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from adapters.source.xmlgen.constants import (
    MIN_JAVA_MAJOR,
    XMLGEN_COMMIT,
    XMLGEN_REPO,
    XMLGEN_SPARSE_PATH,
)
from adapters.source.xmlgen.resolve import resolve_java
from core.diagnostics import Diagnostic, error
from core.toolchain.fetchers import (
    find_git,
    gradlew_cmd,
    install_jar_pair,
    pin_artifact_name,
    run_cmd,
)
from core.toolchain.manifest import ComponentSpec
from core.toolchain.progress import ProgressFn, noop_progress

# Upstream pin ships Gradle 8.5 + johnrengelman shadow 8.1.1, which cannot
# run on JDK 25. Local patches keep a single-JDK toolchain (ADR-013 / sync).
XMLGEN_GRADLE_VERSION = "9.1.0"
XMLGEN_SHADOW_PLUGIN = 'id("com.gradleup.shadow") version "9.0.2"'
_SHADOW_PLUGIN_RE = re.compile(
    r'id\(\s*"(?:com\.github\.johnrengelman\.shadow|com\.gradleup\.shadow)"\s*\)'
    r'\s+version\s+"[^"]+"'
)
_TOOLCHAIN_RE = re.compile(r"JavaLanguageVersion\.of\(\s*\d+\s*\)")
_DIST_URL_RE = re.compile(
    r"(distributionUrl\s*=\s*https\\?://services\.gradle\.org/distributions/)"
    r"gradle-[^\s]+-bin\.zip"
)


def patch_xmlgen_for_jdk25(project: Path) -> None:
    """Rewrite upstream Gradle wrapper + build for host/compile JDK 25."""
    props = project / "gradle" / "wrapper" / "gradle-wrapper.properties"
    if props.is_file():
        text = props.read_text(encoding="utf-8")
        patched = _DIST_URL_RE.sub(
            rf"\1gradle-{XMLGEN_GRADLE_VERSION}-bin.zip",
            text,
            count=1,
        )
        if patched == text and f"gradle-{XMLGEN_GRADLE_VERSION}-bin.zip" not in text:
            # Fallback: replace any distributionUrl line value.
            lines: list[str] = []
            for line in text.splitlines(keepends=True):
                if line.startswith("distributionUrl="):
                    lines.append(
                        "distributionUrl=https\\://services.gradle.org/distributions/"
                        f"gradle-{XMLGEN_GRADLE_VERSION}-bin.zip\n"
                    )
                else:
                    lines.append(line)
            patched = "".join(lines)
        props.write_text(patched, encoding="utf-8")

    build = project / "build.gradle.kts"
    if not build.is_file():
        return
    text = build.read_text(encoding="utf-8")
    if _SHADOW_PLUGIN_RE.search(text):
        text = _SHADOW_PLUGIN_RE.sub(XMLGEN_SHADOW_PLUGIN, text, count=1)
    text = _TOOLCHAIN_RE.sub("JavaLanguageVersion.of(25)", text)
    build.write_text(text, encoding="utf-8")


def fetch_xml_gen(
    spec: ComponentSpec,
    tools_dir: Path,
    *,
    env: dict[str, str] | None = None,
    progress: ProgressFn | None = None,
    quiet: bool = True,
) -> tuple[Path | None, list[Diagnostic]]:
    """Idempotently build xml-gen into tools_dir. Returns (stable_path, diagnostics)."""
    report = progress or noop_progress
    diagnostics: list[Diagnostic] = []
    pin = spec.pin or XMLGEN_COMMIT
    short = pin[:12]
    artifact = spec.artifact
    pinned = tools_dir / pin_artifact_name(artifact, short)
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
                f"Java {min_java}+ не найдена (нужна для xml-gen)",
                code="1CT001",
                source="toolchain",
                suggestion=(
                    "Установите JDK 25+ и задайте JAVA_HOME или добавьте java в PATH "
                    "(единый JDK для всего toolchain)."
                ),
            )
        )
        return None, diagnostics

    git = find_git()
    if not git:
        diagnostics.append(
            error(
                "git не найден (нужен для сборки xml-gen)",
                code="1CT002",
                source="toolchain",
                suggestion="Установите Git и добавьте его в PATH.",
            )
        )
        return None, diagnostics

    repo = str(spec.source.get("repo") or XMLGEN_REPO)
    sparse = str(spec.source.get("sparse_path") or XMLGEN_SPARSE_PATH)

    work = Path(tempfile.mkdtemp(prefix="1c-dev-xmlgen-"))
    try:
        src = work / "src"
        report(f"→ {spec.id}: git clone…")
        clone = run_cmd(
            [git, "clone", "--filter=blob:none", "--sparse", repo, str(src)],
            quiet=quiet,
        )
        if clone.returncode != 0:
            diagnostics.append(
                error(
                    "Не удалось клонировать репозиторий xml-gen",
                    code="1CT003",
                    source="toolchain",
                    suggestion=(clone.stderr or clone.stdout or "").strip()[:500]
                    or "Проверьте сеть и доступ к GitHub.",
                )
            )
            return None, diagnostics

        sparse_set = run_cmd(
            [git, "-C", str(src), "sparse-checkout", "set", sparse],
            quiet=quiet,
        )
        if sparse_set.returncode != 0:
            diagnostics.append(
                error(
                    "git sparse-checkout не удался",
                    code="1CT003",
                    source="toolchain",
                    suggestion=(sparse_set.stderr or "").strip()[:500],
                )
            )
            return None, diagnostics

        checkout = run_cmd(
            [git, "-C", str(src), "checkout", pin],
            quiet=quiet,
        )
        if checkout.returncode != 0:
            diagnostics.append(
                error(
                    f"git checkout {short} не удался",
                    code="1CT003",
                    source="toolchain",
                    suggestion=(checkout.stderr or "").strip()[:500],
                )
            )
            return None, diagnostics

        project = src / Path(sparse)
        wrapper = gradlew_cmd(project)
        if wrapper is None:
            diagnostics.append(
                error(
                    "gradlew не найден в исходниках xml-gen",
                    code="1CT004",
                    source="toolchain",
                )
            )
            return None, diagnostics

        patch_xmlgen_for_jdk25(project)

        run_env = dict(os.environ if env is None else env)
        run_env["JAVA_HOME"] = str(java.path.parent.parent)

        report(f"→ {spec.id}: gradle build…")
        gradle_argv = [*wrapper, "build", "-x", "test", "--no-daemon"]
        if quiet:
            gradle_argv.append("-q")
        build = run_cmd(
            gradle_argv,
            cwd=str(project),
            env=run_env,
            quiet=quiet,
        )
        if build.returncode != 0:
            diagnostics.append(
                error(
                    "Сборка xml-gen через Gradle завершилась с ошибкой",
                    code="1CT004",
                    source="toolchain",
                    suggestion=(build.stderr or build.stdout or "").strip()[:500]
                    or "См. вывод Gradle выше. Нужен JDK 25+.",
                )
            )
            return None, diagnostics

        libs = project / "build" / "libs"
        built_candidates = sorted(libs.glob("xml-gen-*.jar"))
        if not built_candidates:
            diagnostics.append(
                error(
                    "Собранный xml-gen jar не найден",
                    code="1CT004",
                    source="toolchain",
                )
            )
            return None, diagnostics

        stable_path = install_jar_pair(
            built=built_candidates[0],
            tools_dir=tools_dir,
            artifact=artifact,
            pin=short,
        )
        return stable_path, diagnostics
    finally:
        shutil.rmtree(work, ignore_errors=True)
