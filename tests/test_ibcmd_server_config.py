"""Tests for ibcmd server config init (ADR-025 / #89)."""

from __future__ import annotations

from pathlib import Path

from adapters.platform_ibcmd.client import IbcmdRunResult, server_config_init


def test_server_config_init_argv(tmp_path: Path) -> None:
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    out = tmp_path / "publish" / "ibsrv.yaml"
    db_path = tmp_path / "ib"
    db_path.mkdir()
    captured: list[list[str]] = []

    def run(argv: list[str]) -> IbcmdRunResult:
        captured.append(argv)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("server:\n  address: localhost\n  port: 8314\n", encoding="utf-8")
        return IbcmdRunResult(returncode=0, stdout="", stderr="", argv=argv)

    result = server_config_init(
        ibcmd,
        out=out,
        db_path=db_path,
        http_port=8314,
        name="local-ibsrv",
        run=run,
    )
    assert result.returncode == 0
    argv = captured[0]
    assert argv[:4] == [str(ibcmd), "server", "config", "init"]
    assert f"--out={out}" in argv
    assert f"--db-path={db_path}" in argv
    assert "--http-address=localhost" in argv
    assert "--http-port=8314" in argv
    assert "--http-base=/" in argv
    assert "--name=local-ibsrv" in argv
