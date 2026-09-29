"""Tests for ibsrv adapter helpers (ADR-025 / #89)."""

from __future__ import annotations

from pathlib import Path

from adapters.ibsrv.client import (
    IbsrvRunResult,
    build_url,
    clear_lock_pid,
    parse_server_config,
    read_lock_pid,
    start_daemon,
)


def test_start_daemon_argv(tmp_path: Path) -> None:
    ibsrv = tmp_path / "ibsrv"
    ibsrv.write_text("", encoding="utf-8")
    config = tmp_path / "ibsrv.yaml"
    config.write_text("server: {}\n", encoding="utf-8")
    data = tmp_path / "data"
    captured: list[list[str]] = []

    def run(argv: list[str]) -> IbsrvRunResult:
        captured.append(argv)
        return IbsrvRunResult(returncode=0, stdout="", stderr="", argv=argv)

    result = start_daemon(ibsrv, config=config, data=data, run=run)
    assert result.returncode == 0
    assert data.is_dir()
    argv = captured[0]
    assert argv[0] == str(ibsrv)
    assert "--daemon" in argv
    assert f"--config={config}" in argv
    assert f"--data={data}" in argv
    assert "--disable-direct-gate" in argv
    assert "--disable-ssh-gate" in argv


def test_lock_pid_roundtrip(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    assert read_lock_pid(data) is None
    (data / "lock.pid").write_text("4242\n", encoding="utf-8")
    assert read_lock_pid(data) == 4242
    clear_lock_pid(data)
    assert read_lock_pid(data) is None


def test_build_url_from_yaml(tmp_path: Path) -> None:
    config = tmp_path / "ibsrv.yaml"
    config.write_text(
        "\n".join(
            [
                "server:",
                "  address: localhost",
                "  port: 8314",
                "http:",
                "  base: /",
                "database:",
                "  path: /abs/ib",
            ]
        ),
        encoding="utf-8",
    )
    parsed = parse_server_config(config)
    assert build_url(parsed) == "http://localhost:8314/"
