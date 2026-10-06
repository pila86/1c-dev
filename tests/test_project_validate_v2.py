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
    data["publish"]["profiles"]["local-webinst"]["runtime"] = "no-such-rt"


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


def _base_with_test_extensions() -> dict[str, Any]:
    """Minimal schema-2 manifest with test-extensions (ADR-029)."""
    return {
        "schema": "2",
        "project": {"name": "shop"},
        "platform": {"version": "8.3.27"},
        "configurations": [
            {
                "id": "main",
                "type": "configuration",
                "default": True,
                "source": {"format": "xml", "path": "src/cf"},
                "extensions": [
                    {
                        "id": "yaxunit",
                        "name": "YAXUNIT",
                        "purpose": "tests",
                        "source": {"format": "xml", "path": "src/cfe/yaxunit"},
                    },
                    {
                        "id": "test_ext1",
                        "name": "Tests1",
                        "purpose": "tests",
                        "source": {"format": "xml", "path": "src/cfe/test_ext1"},
                    },
                    {
                        "id": "custom",
                        "name": "CustomExt",
                        "purpose": "product",
                        "source": {"format": "xml", "path": "src/cfe/custom"},
                    },
                ],
                "tests": [
                    {
                        "id": "unit",
                        "runner": "yaxunit",
                        "extensions": ["test_ext1"],
                    }
                ],
            }
        ],
        "runtimes": [
            {
                "id": "main-dev",
                "configuration": "main",
                "type": "file",
                "path": ".1c-dev/runtime/main",
                "default": True,
            }
        ],
    }


def test_validate_manifest_tests_ok() -> None:
    assert validate_manifest(_base_with_test_extensions()) == []


def test_validate_manifest_tests_vanessa_runner_ok() -> None:
    data = _base_with_test_extensions()
    data["configurations"][0]["tests"][0]["runner"] = "vanessa"
    assert validate_manifest(data) == []


def test_validate_manifest_tests_absent_ok() -> None:
    """Additive schema \"2\": без configurations[].tests — валидно (M4)."""
    data = _base_with_test_extensions()
    del data["configurations"][0]["tests"]
    assert validate_manifest(data) == []


def test_validate_manifest_tests_empty_array_ok() -> None:
    data = _base_with_test_extensions()
    data["configurations"][0]["tests"] = []
    assert validate_manifest(data) == []


def _tests_missing_id(data: dict[str, Any]) -> None:
    del data["configurations"][0]["tests"][0]["id"]


def _tests_bad_runner(data: dict[str, Any]) -> None:
    data["configurations"][0]["tests"][0]["runner"] = "junit"


def _tests_empty_extensions(data: dict[str, Any]) -> None:
    data["configurations"][0]["tests"][0]["extensions"] = []


def _tests_duplicate_extension_refs(data: dict[str, Any]) -> None:
    data["configurations"][0]["tests"][0]["extensions"] = [
        "test_ext1",
        "test_ext1",
    ]


def _tests_unknown_extension(data: dict[str, Any]) -> None:
    data["configurations"][0]["tests"][0]["extensions"] = ["ghost"]


def _tests_product_purpose(data: dict[str, Any]) -> None:
    data["configurations"][0]["tests"][0]["extensions"] = ["custom"]


def _tests_includes_yaxunit(data: dict[str, Any]) -> None:
    data["configurations"][0]["tests"][0]["extensions"] = ["yaxunit"]


def _tests_duplicate_suite_id(data: dict[str, Any]) -> None:
    data["configurations"][0]["tests"].append(
        {
            "id": "unit",
            "runner": "yaxunit",
            "extensions": ["test_ext1"],
        }
    )


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (_tests_missing_id, "tests"),
        (_tests_bad_runner, "tests"),
        (_tests_empty_extensions, "tests"),
        (_tests_duplicate_extension_refs, "tests"),
        (_tests_unknown_extension, "нет extension с id 'ghost'"),
        (_tests_product_purpose, "purpose: tests"),
        (_tests_includes_yaxunit, "не включать runner-extension"),
        (_tests_duplicate_suite_id, "дублируется id 'unit'"),
    ],
)
def test_validate_manifest_tests_invalid(mutate: Mutator, needle: str) -> None:
    data = _base_with_test_extensions()
    mutate(data)
    diags = validate_manifest(data)
    assert diags
    assert all(d.get("code") == "1CP003" for d in diags)
    assert any(needle in d["message"] for d in diags), diags
