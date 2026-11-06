"""Integration smoke: 1cedtcli export/import on edt_spike (#149)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from adapters.edtcli import discover_edtcli

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "edt_spike"
_TIMEOUT = 300


def _require_edtcli() -> Path:
    info = discover_edtcli()
    if not info.found or info.path is None:
        pytest.skip("1cedtcli не найден — EDT smoke пропущен (ONEC_EDTCLI / PATH / components)")
    return info.path


def _run_edt(
    edtcli: Path,
    workspace: Path,
    *command: str,
) -> subprocess.CompletedProcess[str]:
    workspace.mkdir(parents=True, exist_ok=True)
    argv = [
        str(edtcli),
        "-data",
        str(workspace),
        "-timeout",
        str(_TIMEOUT),
        "-command",
        *command,
    ]
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT + 60,
    )


@pytest.mark.integration
def test_edt_export_import_roundtrip(tmp_path: Path) -> None:
    """Export edt_spike → XML; import XML → fresh EDT project (fresh -data each)."""
    edtcli = _require_edtcli()
    if not FIXTURE.is_dir():
        pytest.fail(f"fixture missing: {FIXTURE}")

    export_ws = tmp_path / "ws-export"
    export_xml = tmp_path / "export_xml"
    export_xml.mkdir()

    exported = _run_edt(
        edtcli,
        export_ws,
        "export",
        "--project",
        str(FIXTURE),
        "--configuration-files",
        str(export_xml),
    )
    assert exported.returncode == 0, (
        f"export rc={exported.returncode}\nstdout:\n{exported.stdout}\nstderr:\n{exported.stderr}"
    )
    configuration_xml = export_xml / "Configuration.xml"
    products_xml = export_xml / "Catalogs" / "Products.xml"
    assert configuration_xml.is_file() and configuration_xml.stat().st_size > 0
    assert products_xml.is_file()
    cfg_text = configuration_xml.read_text(encoding="utf-8-sig")
    assert 'version="2.17"' in cfg_text
    assert "Products" in cfg_text

    import_ws = tmp_path / "ws-import"
    import_project = tmp_path / "imported"
    import_project.mkdir()
    imported = _run_edt(
        edtcli,
        import_ws,
        "import",
        "--version",
        "8.5.1",
        "--configuration-files",
        str(export_xml),
        "--project",
        str(import_project),
    )
    assert imported.returncode == 0, (
        f"import rc={imported.returncode}\nstdout:\n{imported.stdout}\nstderr:\n{imported.stderr}"
    )
    assert (import_project / ".project").is_file()
    assert (import_project / "DT-INF" / "PROJECT.PMF").is_file()
    assert (import_project / "src" / "Configuration" / "Configuration.mdo").is_file()
    assert (import_project / "src" / "Catalogs" / "Products" / "Products.mdo").is_file()


@pytest.mark.integration
def test_edt_import_collision_returns_204(tmp_path: Path) -> None:
    """Re-import same --project-name into the same -data → rc 204."""
    edtcli = _require_edtcli()

    # Need Designer XML once (reuse export from fixture).
    export_ws = tmp_path / "ws-export"
    export_xml = tmp_path / "export_xml"
    export_xml.mkdir()
    exported = _run_edt(
        edtcli,
        export_ws,
        "export",
        "--project",
        str(FIXTURE),
        "--configuration-files",
        str(export_xml),
    )
    assert exported.returncode == 0, exported.stderr

    collide_ws = tmp_path / "ws-collide"
    first = _run_edt(
        edtcli,
        collide_ws,
        "import",
        "--version",
        "8.5.1",
        "--configuration-files",
        str(export_xml),
        "--project-name",
        "EdtSpikeCollide",
    )
    assert first.returncode == 0, first.stderr

    second = _run_edt(
        edtcli,
        collide_ws,
        "import",
        "--version",
        "8.5.1",
        "--configuration-files",
        str(export_xml),
        "--project-name",
        "EdtSpikeCollide",
    )
    assert second.returncode == 204, (
        f"expected 204 on workspace collision, got {second.returncode}\n"
        f"stdout:\n{second.stdout}\nstderr:\n{second.stderr}"
    )
    combined = f"{second.stdout}\n{second.stderr}"
    assert "уже существует" in combined or "already exists" in combined.lower()

