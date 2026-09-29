"""Unit tests for apache toolchain resolve / fetch (#94)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.toolchain.fetchers.apache import (
    fetch_apache,
    httpd_binary,
    is_bundled_apache_home,
)
from core.toolchain.manifest import ComponentSpec
from core.toolchain.resolve import resolve_apache_home


def _spec(**source: object) -> ComponentSpec:
    base_source: dict = {"type": "apache-home", "urls": {}}
    base_source.update(source)
    return ComponentSpec(
        id="apache",
        artifact="apache",
        pin="2.4.68",
        source=base_source,
        env="ONEC_APACHE_HOME",
    )


def _make_bundled_home(home: Path) -> Path:
    bin_dir = home / "bin"
    modules = home / "modules"
    bin_dir.mkdir(parents=True)
    modules.mkdir(parents=True)
    httpd = bin_dir / "httpd"
    httpd.write_text("#!/bin/sh\n", encoding="utf-8")
    httpd.chmod(0o755)
    (modules / "mod_mpm_event.so").write_bytes(b"")
    return home


def test_is_bundled_apache_home_requires_modules(tmp_path: Path) -> None:
    thin = tmp_path / "thin"
    (thin / "bin").mkdir(parents=True)
    httpd = thin / "bin" / "httpd"
    httpd.write_text("#!/bin/sh\nexec /usr/sbin/apache2 \"$@\"\n", encoding="utf-8")
    httpd.chmod(0o755)
    assert is_bundled_apache_home(thin) is False

    bundled = _make_bundled_home(tmp_path / "bundled")
    assert is_bundled_apache_home(bundled) is True


def test_resolve_apache_home_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _make_bundled_home(tmp_path / "my-apache")
    monkeypatch.setenv("ONEC_APACHE_HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "empty-cache"))
    resolved = resolve_apache_home(env=dict(**{k: v for k, v in __import__("os").environ.items()}))
    assert resolved.found is True
    assert resolved.httpd is not None
    assert resolved.home == home.resolve()
    assert resolved.source == "env"


def test_fetch_apache_cache_hit_bundled(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    _make_bundled_home(tools / "apache")
    path, diags = fetch_apache(_spec(), tools, env={})
    assert path is not None
    assert httpd_binary(path) is not None
    assert not diags


def test_fetch_apache_skips_thin_wrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = tmp_path / "tools"
    thin = tools / "apache"
    (thin / "bin").mkdir(parents=True)
    httpd = thin / "bin" / "httpd"
    httpd.write_text("#!/bin/sh\nexec /usr/sbin/apache2 \"$@\"\n", encoding="utf-8")
    httpd.chmod(0o755)

    def boom(**_kwargs: object) -> Path:
        raise AssertionError("build must not run in this unit test")

    import core.toolchain.fetchers.apache as apache_mod

    monkeypatch.setattr(apache_mod, "_build_from_source", boom)
    monkeypatch.setattr(apache_mod, "_build_urls", lambda _spec: None)
    monkeypatch.setattr(apache_mod, "_archive_urls", lambda _spec: [])

    path, diags = fetch_apache(_spec(), tools, env={})
    assert path is None
    assert any(d.get("code") == "1CT041" for d in diags)


def test_fetch_apache_builds_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = tmp_path / "tools"
    built = _make_bundled_home(tmp_path / "built-prefix")

    def fake_build(*, urls: dict[str, str], tools_dir: Path, pin: str, report: object) -> Path:
        del urls, report
        target = tools_dir / "apache"
        if target.exists():
            import shutil

            shutil.rmtree(target)
        import shutil

        shutil.copytree(built, target)
        pinned = tools_dir / f"apache-{pin}"
        if pinned.exists():
            shutil.rmtree(pinned)
        shutil.copytree(target, pinned)
        return target.resolve()

    import core.toolchain.fetchers.apache as apache_mod

    monkeypatch.setattr(apache_mod, "_build_from_source", fake_build)
    monkeypatch.setattr(
        apache_mod,
        "_build_urls",
        lambda _spec: {
            "httpd": "https://example.test/httpd.tar.gz",
            "apr": "https://example.test/apr.tar.gz",
            "apr_util": "https://example.test/apu.tar.gz",
        },
    )

    path, diags = fetch_apache(_spec(), tools, env={})
    assert path is not None
    assert is_bundled_apache_home(path)
    assert not diags or all(d.get("severity") != "error" for d in diags)
