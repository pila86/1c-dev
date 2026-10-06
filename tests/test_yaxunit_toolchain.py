"""Toolchain: YAxUnit.cfe in user cache (ADR-029 §7a)."""

from __future__ import annotations

import hashlib
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from core.toolchain.fetchers import pin_artifact_name
from core.toolchain.fetchers.yaxunit import fetch_yaxunit
from core.toolchain.manifest import ComponentSpec, ToolchainManifest, load_manifest
from core.toolchain.resolve import resolve_yaxunit_cfe
from core.toolchain.sync import sync_tools

PAYLOAD = b"fake-cfe-payload"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _spec(*, sha256: str | None = PAYLOAD_SHA) -> ComponentSpec:
    return ComponentSpec(
        id="yaxunit",
        artifact="yaxunit.cfe",
        pin="25.12",
        source={"type": "github-release", "url": "https://example.invalid/YAxUnit-25.12.cfe"},
        env="ONEC_YAXUNIT_CFE",
        sha256=sha256,
    )


def _fake_urlretrieve(payload: bytes = PAYLOAD) -> Any:
    def _retrieve(url: str, dest: Path) -> tuple[str, None]:
        del url
        Path(dest).write_bytes(payload)
        return str(dest), None

    return _retrieve


def test_pin_artifact_name_cfe() -> None:
    assert pin_artifact_name("yaxunit.cfe", "25.12") == "yaxunit-25.12.cfe"
    assert pin_artifact_name("xml-gen.jar", "abc") == "xml-gen-abc.jar"


def test_manifest_has_yaxunit_soft_component() -> None:
    spec = load_manifest().get("yaxunit")
    assert spec is not None
    assert spec.artifact == "yaxunit.cfe"
    assert spec.env == "ONEC_YAXUNIT_CFE"
    assert spec.sha256


def test_fetch_downloads_and_installs_pair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("urllib.request.urlretrieve", _fake_urlretrieve())
    path, diags = fetch_yaxunit(_spec(), tmp_path)
    assert diags == []
    assert path == (tmp_path / "yaxunit.cfe").resolve()
    assert (tmp_path / "yaxunit-25.12.cfe").read_bytes() == PAYLOAD
    assert path.read_bytes() == PAYLOAD
    assert list(tmp_path.glob("yaxunit-*.cfe")) == [tmp_path / "yaxunit-25.12.cfe"]


def test_fetch_cache_hit_does_not_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "yaxunit-25.12.cfe").write_bytes(PAYLOAD)

    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("must not download on cache hit")

    monkeypatch.setattr("urllib.request.urlretrieve", boom)
    path, diags = fetch_yaxunit(_spec(), tmp_path)
    assert diags == []
    assert path is not None and path.read_bytes() == PAYLOAD


def test_fetch_sha_mismatch_after_download_is_soft_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("urllib.request.urlretrieve", _fake_urlretrieve(b"other"))
    path, diags = fetch_yaxunit(_spec(), tmp_path)
    assert path is None
    assert [d["code"] for d in diags] == ["1CT021"]
    assert not (tmp_path / "yaxunit.cfe").exists()
    assert not list(tmp_path.glob("yaxunit-*"))


def test_fetch_network_error_is_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(*_a: Any, **_k: Any) -> None:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlretrieve", fail)
    path, diags = fetch_yaxunit(_spec(), tmp_path)
    assert path is None
    assert diags[0]["code"] == "1CT022"
    assert "ONEC_YAXUNIT_CFE" in (diags[0].get("suggestion") or "")


def test_sync_marks_yaxunit_soft(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("urllib.request.urlretrieve", lambda *_a, **_k: (_ for _ in ()).throw(
        urllib.error.URLError("offline")
    ))
    manifest = ToolchainManifest(version=1, components=(_spec(),))
    result = sync_tools(manifest=manifest)
    assert result.status == "degraded"
    assert result.components[0].id == "yaxunit"
    assert result.components[0].status == "warning"


def test_resolve_prefers_env_then_cache(tmp_path: Path) -> None:
    manifest = ToolchainManifest(version=1, components=(_spec(),))
    cache_env = {"XDG_CACHE_HOME": str(tmp_path / "xdg")}

    missing = resolve_yaxunit_cfe(env={}, cache_env=cache_env, manifest=manifest)
    assert missing.found is False

    tools = tmp_path / "xdg" / "1c-dev" / "tools"
    tools.mkdir(parents=True)
    (tools / "yaxunit-25.12.cfe").write_bytes(PAYLOAD)
    cached = resolve_yaxunit_cfe(env={}, cache_env=cache_env, manifest=manifest)
    assert cached.found is True
    assert cached.source == "cache"
    assert cached.pin == "25.12"

    override = tmp_path / "custom.cfe"
    override.write_bytes(b"x")
    from_env = resolve_yaxunit_cfe(
        env={"ONEC_YAXUNIT_CFE": str(override)}, cache_env=cache_env, manifest=manifest
    )
    assert from_env.found is True
    assert from_env.source == "env"
    assert from_env.path == override.resolve()
