"""Unit tests for adapters.apache scaffold / start (#94)."""

from __future__ import annotations

from pathlib import Path

from adapters.apache.client import (
    ApacheRunResult,
    scaffold_httpd_conf,
    start_httpd,
)


def test_scaffold_httpd_conf(tmp_path: Path) -> None:
    modules = tmp_path / "modules"
    modules.mkdir()
    (modules / "mod_mpm_event.so").write_bytes(b"")
    (modules / "mod_authz_core.so").write_bytes(b"")
    (modules / "mod_alias.so").write_bytes(b"")
    ws = tmp_path / "wsap24.so"
    ws.write_bytes(b"")
    profile = tmp_path / "profile"
    conf = profile / "httpd.conf"
    path = scaffold_httpd_conf(
        conf,
        server_root=profile,
        port=8315,
        modules_dir=modules,
        ws_module=ws,
    )
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "Listen 127.0.0.1:8315" in text
    assert "LoadModule _1cws_module" in text
    assert str(ws.resolve()) in text
    assert "TypesConfig" in text or "mime_module" not in text
    assert "LogFormat" in text
    # LoadModule must appear before LogFormat (ASF shared log_config).
    assert text.index("LoadModule") < text.index("LogFormat")
    assert (profile / "www").is_dir()
    assert (profile / "logs").is_dir()


def test_scaffold_loads_log_config_when_present(tmp_path: Path) -> None:
    modules = tmp_path / "modules"
    modules.mkdir()
    for name in (
        "mod_mpm_event.so",
        "mod_authz_core.so",
        "mod_log_config.so",
        "mod_unixd.so",
        "mod_alias.so",
    ):
        (modules / name).write_bytes(b"")
    conf = tmp_path / "profile" / "httpd.conf"
    scaffold_httpd_conf(
        conf,
        server_root=tmp_path / "profile",
        port=8315,
        modules_dir=modules,
        ws_module=None,
    )
    text = conf.read_text(encoding="utf-8")
    assert "log_config_module" in text
    assert "unixd_module" in text
    assert text.index("log_config_module") < text.index("LogFormat")


def test_start_httpd_argv(tmp_path: Path) -> None:
    httpd = tmp_path / "httpd"
    httpd.write_text("", encoding="utf-8")
    conf = tmp_path / "httpd.conf"
    conf.write_text("", encoding="utf-8")
    captured: list[list[str]] = []

    def run(argv: list[str]) -> ApacheRunResult:
        captured.append(argv)
        return ApacheRunResult(0, "", "", argv)

    start_httpd(httpd, conf=conf, server_root=tmp_path, run=run)
    assert captured[0][:3] == [str(httpd), "-f", str(conf.resolve())]
    assert "-d" in captured[0]
