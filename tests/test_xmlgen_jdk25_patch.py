"""Unit tests for xml-gen JDK 25 Gradle patch."""

from __future__ import annotations

from pathlib import Path

from core.toolchain.fetchers.xmlgen import (
    XMLGEN_GRADLE_VERSION,
    patch_xmlgen_for_jdk25,
)


def test_patch_xmlgen_for_jdk25_rewrites_wrapper_and_build(tmp_path: Path) -> None:
    project = tmp_path / "xml-gen"
    wrapper = project / "gradle" / "wrapper"
    wrapper.mkdir(parents=True)
    props = wrapper / "gradle-wrapper.properties"
    props.write_text(
        "distributionBase=GRADLE_USER_HOME\n"
        "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.5-bin.zip\n"
        "zipStoreBase=GRADLE_USER_HOME\n",
        encoding="utf-8",
    )
    build = project / "build.gradle.kts"
    build.write_text(
        'plugins {\n'
        '    java\n'
        '    id("com.github.johnrengelman.shadow") version "8.1.1"\n'
        "}\n"
        "java {\n"
        "    toolchain {\n"
        "        languageVersion.set(JavaLanguageVersion.of(17))\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    patch_xmlgen_for_jdk25(project)

    props_text = props.read_text(encoding="utf-8")
    assert f"gradle-{XMLGEN_GRADLE_VERSION}-bin.zip" in props_text
    assert "gradle-8.5-bin.zip" not in props_text

    build_text = build.read_text(encoding="utf-8")
    assert 'id("com.gradleup.shadow") version "9.0.2"' in build_text
    assert "johnrengelman" not in build_text
    assert "JavaLanguageVersion.of(25)" in build_text
    assert "JavaLanguageVersion.of(17)" not in build_text


def test_patch_xmlgen_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "xml-gen"
    (project / "gradle" / "wrapper").mkdir(parents=True)
    props = project / "gradle" / "wrapper" / "gradle-wrapper.properties"
    props.write_text(
        f"distributionUrl=https\\://services.gradle.org/distributions/"
        f"gradle-{XMLGEN_GRADLE_VERSION}-bin.zip\n",
        encoding="utf-8",
    )
    build = project / "build.gradle.kts"
    build.write_text(
        'id("com.gradleup.shadow") version "9.0.2"\n'
        "JavaLanguageVersion.of(25)\n",
        encoding="utf-8",
    )
    patch_xmlgen_for_jdk25(project)
    patch_xmlgen_for_jdk25(project)
    assert build.read_text(encoding="utf-8").count("com.gradleup.shadow") == 1
    assert f"gradle-{XMLGEN_GRADLE_VERSION}-bin.zip" in props.read_text(encoding="utf-8")
