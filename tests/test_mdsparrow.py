"""Unit / smoke for md-sparrow resolve + apply-mutation (#153)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from adapters.edtcli.constants import MD_SPARROW_JDK_SKIP_MESSAGE
from adapters.source.mdsparrow import (
    ENV_UNAVAILABLE_CODE,
    MDSPARROW_JAR_ENV,
    MUTATION_FAILED_CODE,
    MdSparrowError,
    apply_mutation,
    resolve_jar,
    resolve_java,
)
from adapters.source.mdsparrow.resolve import ToolResolve

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "edt_spike"
_VSCODE_JAR = Path.home() / (
    ".config/Code/User/globalStorage/yellow-hammer.1c-platform-tools/"
    "md-sparrow/v0.6.7/md-sparrow-0.6.7-all.jar"
)


def test_resolve_jar_prefers_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    jar = tmp_path / "custom-md-sparrow.jar"
    jar.write_bytes(b"jar")
    monkeypatch.setenv(MDSPARROW_JAR_ENV, str(jar))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    resolved = resolve_jar()
    assert resolved.found is True
    assert resolved.path == jar.resolve()


def test_resolve_jar_cache_stable_and_pinned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(MDSPARROW_JAR_ENV, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    tools = tmp_path / "xdg" / "1c-dev" / "tools"
    tools.mkdir(parents=True)
    pinned = tools / "md-sparrow-0.6.7.jar"
    pinned.write_bytes(b"pinned")
    resolved = resolve_jar()
    assert resolved.found is True
    assert resolved.path == pinned.resolve()

    stable = tools / "md-sparrow.jar"
    stable.write_bytes(b"stable")
    resolved2 = resolve_jar()
    assert resolved2.path == stable.resolve()


def test_resolve_jar_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(MDSPARROW_JAR_ENV, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "empty"))
    resolved = resolve_jar()
    assert resolved.found is False


def test_apply_mutation_missing_java_raises_1cs008(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    jar = tmp_path / "md-sparrow.jar"
    jar.write_bytes(b"x")
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_java",
        lambda **_k: ToolResolve(found=False),
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_jar",
        lambda **_k: ToolResolve(found=True, path=jar),
    )
    with pytest.raises(MdSparrowError) as exc:
        apply_mutation({"op": "add-md-object"})
    assert exc.value.code == ENV_UNAVAILABLE_CODE


def test_apply_mutation_missing_jar_raises_1cs008(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_java",
        lambda **_k: ToolResolve(found=True, path=Path("/usr/bin/java"), version="25"),
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_jar",
        lambda **_k: ToolResolve(found=False),
    )
    with pytest.raises(MdSparrowError) as exc:
        apply_mutation({"op": "add-md-object"})
    assert exc.value.code == ENV_UNAVAILABLE_CODE


def test_apply_mutation_subprocess_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    jar = tmp_path / "md-sparrow.jar"
    jar.write_bytes(b"x")
    java = tmp_path / "java"
    java.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_java",
        lambda **_k: ToolResolve(found=True, path=java, version="25"),
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_jar",
        lambda **_k: ToolResolve(found=True, path=jar),
    )
    proc = MagicMock()
    proc.returncode = 2
    proc.stdout = ""
    proc.stderr = "boom"
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.subprocess.run",
        lambda *_a, **_k: proc,
    )
    with pytest.raises(MdSparrowError) as exc:
        apply_mutation({"op": "add-md-object", "name": "X"})
    assert exc.value.code == MUTATION_FAILED_CODE
    assert "boom" in exc.value.message


def test_apply_mutation_success_mocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    jar = tmp_path / "md-sparrow.jar"
    jar.write_bytes(b"x")
    java = tmp_path / "java"
    java.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_java",
        lambda **_k: ToolResolve(found=True, path=java, version="25"),
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_jar",
        lambda **_k: ToolResolve(found=True, path=jar),
    )
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        out = MagicMock()
        out.returncode = 0
        out.stdout = "ok"
        out.stderr = ""
        return out

    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.subprocess.run",
        fake_run,
    )
    result = apply_mutation({"op": "add-md-object", "name": "Partners"})
    assert result.stdout == "ok"
    assert captured["cmd"][0] == str(java)
    assert captured["cmd"][1] == "-jar"
    assert captured["cmd"][2] == str(jar)
    assert captured["cmd"][3] == "apply-mutation"
    assert captured["cmd"][4].startswith("--params=")


def _require_mdsparrow_runtime() -> tuple[ToolResolve, ToolResolve]:
    java = resolve_java()
    if not java.found:
        pytest.skip(MD_SPARROW_JDK_SKIP_MESSAGE)
    jar = resolve_jar()
    if not jar.found and _VSCODE_JAR.is_file():
        jar = ToolResolve(found=True, path=_VSCODE_JAR.resolve())
    if not jar.found:
        pytest.skip(
            "md-sparrow jar не найден — выполните 1c-dev tools sync "
            f"или задайте {MDSPARROW_JAR_ENV}"
        )
    return java, jar


@pytest.mark.integration
def test_apply_mutation_smoke_on_edt_spike(tmp_path: Path) -> None:
    """Live apply-mutation add-md-object on a copy of edt_spike fixture."""
    java, jar = _require_mdsparrow_runtime()
    root = tmp_path / "edt_spike"
    shutil.copytree(_FIXTURE, root)
    cfg = root / "src" / "Configuration" / "Configuration.mdo"
    assert cfg.is_file()
    partners = root / "src" / "Catalogs" / "Partners" / "Partners.mdo"
    assert not partners.exists()

    apply_mutation(
        {
            "op": "add-md-object",
            "configurationXml": str(cfg.resolve()),
            "type": "CATALOG",
            "name": "Partners",
            "synonymRu": "Партнёры",
            "schemaVersion": "V2_17",
        },
        jar=jar,
        java=java,
    )
    assert partners.is_file()
    text = partners.read_text(encoding="utf-8")
    assert "mdclass:Catalog" in text
    assert "<name>Partners</name>" in text
    cfg_text = cfg.read_text(encoding="utf-8")
    assert "Catalog.Partners" in cfg_text
