"""Runner ensure: YAXUNIT from cache + safe-mode off (ADR-029 §7a)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from adapters.platform_ibcmd.client import IbcmdRunResult
from adapters.platform_ibcmd.constants import IB_MARKER
from core.test.constants import (
    CODE_IB_MISSING,
    CODE_IBCMD_MISSING,
    CODE_RUNNER_CFE_MISSING,
    CODE_RUNNER_ENSURE_FAILED,
    CODE_TEST_EXT_MISSING,
)
from core.test.runner_ensure import (
    ensure_yaxunit_runner,
    purpose_tests_extension_names,
    runner_state_path,
)
from core.test.suites import SuiteRef
from core.toolchain.resolve import YaxunitResolve

PIN = "25.12"


def _configuration(*, with_yaxunit: bool = False) -> dict[str, Any]:
    exts: list[dict[str, Any]] = [
        {"id": "t1", "name": "Tests1", "purpose": "tests"},
        {"id": "t2", "name": "Tests2", "purpose": "tests"},
        {"id": "prod", "name": "Prod", "purpose": "product"},
    ]
    if with_yaxunit:
        exts.append({"id": "yaxunit", "name": "YAXUNIT", "purpose": "tests"})
    return {"id": "main", "extensions": exts}


def _suite(runner: str = "yaxunit") -> SuiteRef:
    return SuiteRef(id="unit", runner=runner, extensions=())


@dataclass
class FakeIb:
    """Tiny in-memory stand-in for ibcmd extension list/load/update."""

    extensions: dict[str, dict[str, str]]
    calls: list[list[str]]
    fail_on: str | None = None

    def add(self, name: str, *, safe: str = "yes", version: str = "") -> None:
        self.extensions[name] = {
            "version": version,
            "safe-mode": safe,
            "unsafe-action-protection": safe,
        }

    def __call__(self, argv: list[str]) -> IbcmdRunResult:
        self.calls.append(argv)
        key = " ".join(argv[1:3])
        if self.fail_on and self.fail_on in " ".join(argv):
            return IbcmdRunResult(returncode=1, stdout="", stderr="boom", argv=argv)
        if key == "extension list":
            blocks = []
            for name, props in self.extensions.items():
                blocks.append(
                    f'name : "{name}"\nversion : "{props["version"]}"\n'
                    f"safe-mode : {props['safe-mode']}\n"
                    f"unsafe-action-protection : {props['unsafe-action-protection']}\n"
                )
            return IbcmdRunResult(0, "\n".join(blocks), "", argv)
        if key == "extension update":
            name = next(a.split("=", 1)[1] for a in argv if a.startswith("--name="))
            self.extensions[name]["safe-mode"] = "no"
            self.extensions[name]["unsafe-action-protection"] = "no"
        if key == "infobase config" and "load" in argv:
            name = next(a.split("=", 1)[1] for a in argv if a.startswith("--extension="))
            self.add(name, safe="yes", version=PIN)
        return IbcmdRunResult(0, "", "", argv)

    def names_called(self, command: str) -> list[str]:
        return [
            next(a.split("=", 1)[1] for a in c if a.startswith("--name="))
            for c in self.calls
            if " ".join(c[1:3]) == command
        ]

    def count(self, *parts: str) -> int:
        return sum(1 for c in self.calls if all(p in c for p in parts))


def _tool(found: bool, path: str = "/usr/bin/ibcmd") -> ToolInfo:
    return ToolInfo(found=found, path=Path(path) if found else None)


def _discovery(*, ibcmd: bool = True) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(found=True, version="8.3.25.1560", path=Path("/opt/1cv8")),
        ibcmd=_tool(ibcmd),
        onecv8=_tool(True, "/usr/bin/1cv8"),
        onecv8c=_tool(False),
        ibsrv=_tool(False),
        webinst=_tool(False),
    )


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "proj"
    db = root / ".1c-dev" / "runtime" / "main"
    db.mkdir(parents=True)
    (db / IB_MARKER).write_bytes(b"")
    cfe = tmp_path / "cache" / "yaxunit.cfe"
    cfe.parent.mkdir()
    cfe.write_bytes(b"cfe-bytes")
    return root, db, cfe


def _resolve(cfe: Path | None) -> Any:
    def inner() -> YaxunitResolve:
        if cfe is None:
            return YaxunitResolve(found=False, env_name="ONEC_YAXUNIT_CFE")
        return YaxunitResolve(found=True, path=cfe, source="cache", pin=PIN)

    return inner


def _ensure(
    tmp_path: Path,
    fake: FakeIb,
    *,
    suites: list[SuiteRef] | None,
    configuration: dict[str, Any] | None = None,
    cfe_present: bool = True,
    ibcmd: bool = True,
) -> Any:
    root, db, cfe = _setup(tmp_path) if not (tmp_path / "proj").exists() else (
        tmp_path / "proj",
        tmp_path / "proj" / ".1c-dev" / "runtime" / "main",
        tmp_path / "cache" / "yaxunit.cfe",
    )
    return ensure_yaxunit_runner(
        root=root,
        configuration=configuration or _configuration(),
        db_path=db,
        suites=suites,
        discover=lambda: _discovery(ibcmd=ibcmd),
        resolve_cfe=_resolve(cfe if cfe_present else None),
        run=fake,
    )


def test_purpose_tests_names() -> None:
    assert purpose_tests_extension_names(_configuration()) == ["Tests1", "Tests2"]
    assert purpose_tests_extension_names({}) == []


def test_skipped_without_yaxunit_suite(tmp_path: Path) -> None:
    fake = FakeIb({}, [])
    result = _ensure(tmp_path, fake, suites=[_suite("vanessa")])
    assert result.status == "skipped"
    assert fake.calls == []
    assert result.to_payload()["reason"]


def test_loads_runner_and_clears_safe_mode(tmp_path: Path) -> None:
    fake = FakeIb({}, [])
    fake.add("Tests1")
    fake.add("Tests2")
    result = _ensure(tmp_path, fake, suites=[_suite()])
    assert result.status == "ok"
    assert result.loaded is True
    assert result.steps[:2] == ["load:YAXUNIT", "apply:YAXUNIT"]
    assert sorted(result.safe_mode_off) == ["Tests1", "Tests2", "YAXUNIT"]
    assert sorted(fake.names_called("extension update")) == ["Tests1", "Tests2", "YAXUNIT"]
    assert all(
        props["safe-mode"] == "no" and props["unsafe-action-protection"] == "no"
        for props in fake.extensions.values()
    )
    # Prod (purpose: product) untouched
    assert "Prod" not in fake.names_called("extension update")
    assert runner_state_path(tmp_path / "proj").is_file()
    payload = result.to_payload()
    assert payload["status"] == "ok"
    assert payload["loaded"] is True
    assert payload["pin"] == PIN
    assert payload["cfePath"].endswith("yaxunit.cfe")


def test_second_run_is_noop(tmp_path: Path) -> None:
    fake = FakeIb({}, [])
    fake.add("Tests1")
    fake.add("Tests2")
    _ensure(tmp_path, fake, suites=[_suite()])
    fake.calls.clear()

    again = _ensure(tmp_path, fake, suites=[_suite()])
    assert again.status == "ok"
    assert again.loaded is False
    assert again.steps == []
    assert again.safe_mode_off == []
    assert fake.count("update") == 0
    assert fake.count("load") == 0


def test_reload_when_cfe_changed(tmp_path: Path) -> None:
    fake = FakeIb({}, [])
    fake.add("Tests1")
    fake.add("Tests2")
    _ensure(tmp_path, fake, suites=[_suite()])
    (tmp_path / "cache" / "yaxunit.cfe").write_bytes(b"new-version")
    fake.calls.clear()

    again = _ensure(tmp_path, fake, suites=[_suite()])
    assert again.loaded is True
    assert fake.count("load") == 1


def test_reload_when_ib_recreated(tmp_path: Path) -> None:
    fake = FakeIb({}, [])
    fake.add("Tests1")
    fake.add("Tests2")
    _ensure(tmp_path, fake, suites=[_suite()])
    # build re-created the IB: YAXUNIT is gone, state file stays
    del fake.extensions["YAXUNIT"]
    fake.add("Tests1")
    fake.add("Tests2")

    again = _ensure(tmp_path, fake, suites=[_suite()])
    assert again.loaded is True
    assert "YAXUNIT" in again.safe_mode_off


def test_existing_runner_with_matching_version_is_trusted(tmp_path: Path) -> None:
    fake = FakeIb({}, [])
    fake.add("YAXUNIT", safe="no", version=PIN)
    fake.add("Tests1", safe="no")
    fake.add("Tests2", safe="no")
    result = _ensure(tmp_path, fake, suites=[_suite()])
    assert result.status == "ok"
    assert result.loaded is False
    assert fake.count("update") == 0


def test_declared_yaxunit_is_not_overwritten(tmp_path: Path) -> None:
    fake = FakeIb({}, [])
    fake.add("YAXUNIT", version="custom")
    fake.add("Tests1")
    fake.add("Tests2")
    result = _ensure(
        tmp_path, fake, suites=[_suite()], configuration=_configuration(with_yaxunit=True)
    )
    assert result.status == "ok"
    assert result.loaded is False
    assert fake.count("load") == 0
    assert "YAXUNIT" in result.safe_mode_off
    assert not runner_state_path(tmp_path / "proj").exists()


def test_missing_test_extension_is_warning(tmp_path: Path) -> None:
    fake = FakeIb({}, [])
    fake.add("Tests1")
    result = _ensure(tmp_path, fake, suites=[_suite()])
    assert result.status == "ok"
    assert [d["code"] for d in result.diagnostics] == [CODE_TEST_EXT_MISSING]
    assert result.diagnostics[0]["severity"] == "warning"


def test_explicit_ensure_without_suites(tmp_path: Path) -> None:
    fake = FakeIb({}, [])
    fake.add("Tests1")
    fake.add("Tests2")
    result = _ensure(tmp_path, fake, suites=None)
    assert result.status == "ok"
    assert result.loaded is True


def test_cfe_missing(tmp_path: Path) -> None:
    fake = FakeIb({}, [])
    result = _ensure(tmp_path, fake, suites=[_suite()], cfe_present=False)
    assert result.status == "failed"
    diag = result.diagnostics[0]
    assert diag["code"] == CODE_RUNNER_CFE_MISSING
    assert "tools sync" in (diag.get("suggestion") or "")
    assert fake.calls == []


def test_ib_missing(tmp_path: Path) -> None:
    fake = FakeIb({}, [])
    root = tmp_path / "proj"
    root.mkdir()
    result = ensure_yaxunit_runner(
        root=root,
        configuration=_configuration(),
        db_path=root / ".1c-dev" / "runtime" / "main",
        suites=[_suite()],
        discover=lambda: _discovery(),
        resolve_cfe=_resolve(None),
        run=fake,
    )
    assert result.status == "failed"
    assert result.diagnostics[0]["code"] == CODE_IB_MISSING


def test_ibcmd_missing(tmp_path: Path) -> None:
    fake = FakeIb({}, [])
    result = _ensure(tmp_path, fake, suites=[_suite()], ibcmd=False)
    assert result.status == "failed"
    assert result.diagnostics[0]["code"] == CODE_IBCMD_MISSING


def test_ibcmd_failure_maps_to_ensure_failed(tmp_path: Path) -> None:
    fake = FakeIb({}, [], fail_on="load")
    result = _ensure(tmp_path, fake, suites=[_suite()])
    assert result.status == "failed"
    assert result.diagnostics[0]["code"] == CODE_RUNNER_ENSURE_FAILED
    assert not runner_state_path(tmp_path / "proj").exists()
