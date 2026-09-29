"""Tests for schema \"2\" validate (ADR-022–026 / #85)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.project.validate import validate_manifest

FIXTURES = Path(__file__).parent / "fixtures"
Mutator = Callable[[dict[str, Any]], None]


def _load_fixture(name: str) -> dict[str, Any]:
    data = yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _drop_buh_runtime(data: dict[str, Any]) -> None:
    data["runtimes"] = [rt for rt in data["runtimes"] if rt["id"] != "buh-dev"]


def _clear_runtime_defaults(data: dict[str, Any]) -> None:
    for rt in data["runtimes"]:
        rt.pop("default", None)


def _add_second_default_runtime(data: dict[str, Any]) -> None:
    data["runtimes"].append(
        {
            "id": "extra",
            "configuration": "main",
            "type": "file",
            "path": ".1c-dev/runtime/extra",
            "default": True,
        }
    )


def _bad_runtime_configuration(data: dict[str, Any]) -> None:
    data["runtimes"][0]["configuration"] = "missing"


def _bad_publish_runtime(data: dict[str, Any]) -> None:
    data["publish"]["profiles"]["local-ibsrv"]["runtime"] = "no-such-rt"


def _bad_publish_default(data: dict[str, Any]) -> None:
    data["publish"]["default"] = "ghost"


def _duplicate_configuration_id(data: dict[str, Any]) -> None:
    data["configurations"].append(
        {
            "id": "main",
            "type": "configuration",
            "source": {"format": "xml", "path": "src/dup"},
        }
    )


def _two_default_configurations(data: dict[str, Any]) -> None:
    data["configurations"][1]["default"] = True


def test_validate_manifest_schema2_ok() -> None:
    assert validate_manifest(_load_fixture("valid_1c.project.v2.yaml")) == []


def test_validate_manifest_schema2_invalid() -> None:
    diags = validate_manifest(_load_fixture("invalid_1c.project.v2.yaml"))
    assert diags
    assert all(d.get("code") == "1CP003" for d in diags)


def test_validate_manifest_unsupported_schema() -> None:
    data = _load_fixture("valid_1c.project.v2.yaml")
    data["schema"] = "99"
    diags = validate_manifest(data)
    assert len(diags) == 1
    assert diags[0]["code"] == "1CP003"
    assert "неподдерживаемая версия" in diags[0]["message"]


def test_validate_manifest_schema1_rejected() -> None:
    data = {
        "schema": "1",
        "project": {"name": "shop", "type": "configuration"},
        "platform": {"version": "8.3.27"},
        "source": {"format": "xml", "path": "src/cf"},
        "runtime": {"type": "file", "path": ".runtime/ib"},
    }
    diags = validate_manifest(data)
    assert diags
    assert diags[0]["code"] == "1CP003"
    assert "неподдерживаемая версия" in diags[0]["message"]


def test_validate_manifest_schema2_jsonschema_error() -> None:
    data = _load_fixture("valid_1c.project.v2.yaml")
    del data["runtimes"]
    diags = validate_manifest(data)
    assert diags
    assert diags[0]["code"] == "1CP003"


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (_drop_buh_runtime, "нет ни одного runtime"),
        (_clear_runtime_defaults, "ровно один элемент с default: true"),
        (_add_second_default_runtime, "ровно один элемент с default: true"),
        (_bad_runtime_configuration, "нет configuration с id 'missing'"),
        (_bad_publish_runtime, "нет runtime с id 'no-such-rt'"),
        (_bad_publish_default, "нет профиля с id 'ghost'"),
        (_duplicate_configuration_id, "дублируется id 'main'"),
        (
            _two_default_configurations,
            "не более одной configuration с default: true",
        ),
    ],
)
def test_validate_manifest_schema2_invariants(mutate: Mutator, needle: str) -> None:
    data = copy.deepcopy(_load_fixture("valid_1c.project.v2.yaml"))
    mutate(data)
    diags = validate_manifest(data)
    assert diags
    assert all(d.get("code") == "1CP003" for d in diags)
    assert any(needle in d["message"] for d in diags), diags


def test_validate_manifest_schema2_empty_scope_ok() -> None:
    """Empty configurations[] / runtimes[] — valid until configuration.add (#100)."""
    data = {
        "schema": "2",
        "project": {"name": "empty", "type": "configuration"},
        "platform": {"version": "8.3.27"},
        "configurations": [],
        "runtimes": [],
    }
    assert validate_manifest(data) == []


def test_validate_manifest_schema2_conf_without_runtime() -> None:
    data = {
        "schema": "2",
        "project": {"name": "shop", "type": "configuration"},
        "platform": {"version": "8.3.27"},
        "configurations": [
            {
                "id": "main",
                "type": "configuration",
                "default": True,
                "source": {"format": "xml", "path": "src/cf"},
            }
        ],
        "runtimes": [],
    }
    diags = validate_manifest(data)
    assert diags
    assert any("нет ни одного runtime" in d["message"] for d in diags)
