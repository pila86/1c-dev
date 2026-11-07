"""Toolchain: md-sparrow jar in user cache (ADR-032 / #153)."""

from __future__ import annotations

import hashlib
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from adapters.source.mdsparrow.constants import MDSPARROW_JAR_ENV, MDSPARROW_PIN
from core.toolchain.fetchers import pin_artifact_name
from core.toolchain.fetchers.mdsparrow import fetch_md_sparrow
from core.toolchain.manifest import ComponentSpec, ToolchainManifest, load_manifest
from core.toolchain.sync import sync_tools

PAYLOAD = b"fake-md-sparrow-jar"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _spec(*, sha256: str | None = PAYLOAD_SHA) -> ComponentSpec:
    return ComponentSpec(
        id="md-sparrow",
        artifact="md-sparrow.jar",
        pin=MDSPARROW_PIN,
        source={
            "type": "github-release",
            "url": "https://example.invalid/md-sparrow-0.6.7-all.jar",
        },
        min_java=25,
        env=MDSPARROW_JAR_ENV,
        sha256=sha256,
    )


def _fake_urlretrieve(payload: bytes = PAYLOAD) -> Any:
    def _retrieve(url: str, dest: Path) -> tuple[str, None]:
        del url
        Path(dest).write_bytes(payload)
        return str(dest), None

    return _retrieve


def test_pin_artifact_name_md_sparrow() -> None:
    assert pin_artifact_name("md-sparrow.jar", "0.6.7") == "md-sparrow-0.6.7.jar"


def test_manifest_has_md_sparrow_soft_component() -> None:
    spec = load_manifest().get("md-sparrow")
    assert spec is not None
    assert spec.artifact == "md-sparrow.jar"
    assert spec.pin == "0.6.7"
    assert spec.env == MDSPARROW_JAR_ENV
    assert spec.min_java == 25
    assert spec.sha256


def test_fetch_downloads_and_installs_pair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("urllib.request.urlretrieve", _fake_urlretrieve())
    path, diags = fetch_md_sparrow(_spec(), tmp_path)
    assert diags == []
    assert path == (tmp_path / "md-sparrow.jar").resolve()
    assert (tmp_path / "md-sparrow-0.6.7.jar").read_bytes() == PAYLOAD
    assert path.read_bytes() == PAYLOAD


def test_fetch_cache_hit_does_not_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "md-sparrow-0.6.7.jar").write_bytes(PAYLOAD)

    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("must not download on cache hit")

    monkeypatch.setattr("urllib.request.urlretrieve", boom)
    path, diags = fetch_md_sparrow(_spec(), tmp_path)
    assert diags == []
    assert path is not None and path.read_bytes() == PAYLOAD


def test_fetch_sha_mismatch_after_download_is_soft_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("urllib.request.urlretrieve", _fake_urlretrieve(b"other"))
    path, diags = fetch_md_sparrow(_spec(), tmp_path)
    assert path is None
    assert [d["code"] for d in diags] == ["1CT021"]
    assert not (tmp_path / "md-sparrow.jar").exists()


def test_fetch_network_error_is_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(*_a: Any, **_k: Any) -> None:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlretrieve", fail)
    path, diags = fetch_md_sparrow(_spec(), tmp_path)
    assert path is None
    assert diags[0]["code"] == "1CT023"
    assert MDSPARROW_JAR_ENV in (diags[0].get("suggestion") or "")


def test_sync_marks_md_sparrow_soft(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(
        "urllib.request.urlretrieve",
        lambda *_a, **_k: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    manifest = ToolchainManifest(version=1, components=(_spec(),))
    result = sync_tools(manifest=manifest)
    assert result.status == "degraded"
    assert result.components[0].id == "md-sparrow"
    assert result.components[0].status == "warning"
