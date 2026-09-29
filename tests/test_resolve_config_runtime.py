"""Unit tests for resolve_config_runtime (#87 / ADR-023 / ADR-026)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from core.project.constants import (
    CODE_CONFIG_AMBIGUOUS,
    CODE_CONFIG_UNKNOWN,
    CODE_RUNTIME_AMBIGUOUS,
    CODE_RUNTIME_CONFIG_MISMATCH,
    CODE_RUNTIME_UNKNOWN,
)
from core.project.resolve import resolve_config_runtime

FIXTURES = Path(__file__).parent / "fixtures"


def _v2() -> dict[str, Any]:
    raw = yaml.safe_load((FIXTURES / "valid_1c.project.v2.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def test_defaults_use_global_default_runtime() -> None:
    target, diags = resolve_config_runtime(_v2())
    assert diags == []
    assert target is not None
    assert target.config_id == "main"
    assert target.runtime_id == "main-dev"
    assert target.source_rel == "src/cf"
    assert target.runtime_rel == ".1c-dev/runtime/main"


def test_config_selects_sole_runtime() -> None:
    target, diags = resolve_config_runtime(_v2(), config_id="buh")
    assert diags == []
    assert target is not None
    assert target.config_id == "buh"
    assert target.runtime_id == "buh-dev"
    assert target.source_rel == "src/buh"
    assert target.runtime_rel == ".1c-dev/runtime/buh"


def test_runtime_selects_linked_configuration() -> None:
    target, diags = resolve_config_runtime(_v2(), runtime_id="buh-dev")
    assert diags == []
    assert target is not None
    assert target.config_id == "buh"
    assert target.runtime_id == "buh-dev"


def test_config_and_runtime_must_agree() -> None:
    target, diags = resolve_config_runtime(
        _v2(),
        config_id="main",
        runtime_id="buh-dev",
    )
    assert target is None
    assert any(d.get("code") == CODE_RUNTIME_CONFIG_MISMATCH for d in diags)


def test_unknown_config_id() -> None:
    target, diags = resolve_config_runtime(_v2(), config_id="nope")
    assert target is None
    assert any(d.get("code") == CODE_CONFIG_UNKNOWN for d in diags)


def test_unknown_runtime_id() -> None:
    target, diags = resolve_config_runtime(_v2(), runtime_id="nope")
    assert target is None
    assert any(d.get("code") == CODE_RUNTIME_UNKNOWN for d in diags)


def test_ambiguous_runtime_for_config_with_many_ibs() -> None:
    data = _v2()
    data["runtimes"].append(
        {
            "id": "main-demo",
            "configuration": "main",
            "type": "file",
            "path": ".1c-dev/runtime/main-demo",
        }
    )
    # Remove global default from main-dev so --config main cannot pick via default.
    data["runtimes"][0].pop("default", None)
    data["runtimes"][1]["default"] = True  # buh-dev is global default (other config)

    target, diags = resolve_config_runtime(data, config_id="main")
    assert target is None
    assert any(d.get("code") == CODE_RUNTIME_AMBIGUOUS for d in diags)


def test_config_with_many_ibs_uses_global_default_when_belongs() -> None:
    data = _v2()
    data["runtimes"].append(
        {
            "id": "main-demo",
            "configuration": "main",
            "type": "file",
            "path": ".1c-dev/runtime/main-demo",
        }
    )
    target, diags = resolve_config_runtime(data, config_id="main")
    assert diags == []
    assert target is not None
    assert target.runtime_id == "main-dev"


def test_ambiguous_configurations_without_default() -> None:
    data = _v2()
    for conf in data["configurations"]:
        conf.pop("default", None)
    target, diags = resolve_config_runtime(data, require_runtime=False)
    assert target is None
    assert any(d.get("code") == CODE_CONFIG_AMBIGUOUS for d in diags)


def test_require_runtime_false_skips_runtime() -> None:
    target, diags = resolve_config_runtime(_v2(), require_runtime=False)
    assert diags == []
    assert target is not None
    assert target.config_id == "main"
    assert target.runtime is None
    assert target.runtime_id is None
    assert target.source_rel == "src/cf"


def test_require_runtime_false_with_config() -> None:
    target, diags = resolve_config_runtime(
        _v2(),
        config_id="buh",
        require_runtime=False,
    )
    assert diags == []
    assert target is not None
    assert target.config_id == "buh"
    assert target.runtime is None
    assert target.source_rel == "src/buh"


def test_schema1_rejected() -> None:
    data = {
        "schema": "1",
        "project": {"name": "shop", "type": "configuration"},
        "platform": {"version": "8.3.27"},
        "source": {"format": "xml", "path": "src/cf"},
        "runtime": {"type": "file", "path": ".runtime/ib"},
    }
    target, diags = resolve_config_runtime(data)
    assert target is None
    assert any(d.get("code") == CODE_CONFIG_UNKNOWN for d in diags)
    assert any("Неподдерживаемая версия schema" in d["message"] for d in diags)


def test_agreed_config_and_runtime() -> None:
    target, diags = resolve_config_runtime(
        _v2(),
        config_id="main",
        runtime_id="main-dev",
    )
    assert diags == []
    assert target is not None
    assert target.config_id == "main"
    assert target.runtime_id == "main-dev"


def test_no_flags_follow_default_runtime_not_unrelated_config() -> None:
    """Global default runtime wins even if another config is marked default."""
    data = copy.deepcopy(_v2())
    # Flip: buh is default config, but main-dev remains default runtime.
    for conf in data["configurations"]:
        conf["default"] = conf["id"] == "buh"
    target, diags = resolve_config_runtime(data)
    assert diags == []
    assert target is not None
    assert target.runtime_id == "main-dev"
    assert target.config_id == "main"
