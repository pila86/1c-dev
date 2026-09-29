"""Shared test helpers for bootstrapping a configuration project (#100)."""

from __future__ import annotations

from pathlib import Path

from core.configuration import add_configuration
from core.project import init_project
from core.project.result import ProjectResult


def bootstrap_configuration_project(
    target: Path,
    *,
    name: str = "Shop",
    ide_target: str = "all",
    force: bool = False,
) -> ProjectResult:
    """
    Empty ``project.init`` + ``configuration.add`` with id=main, path=src/cf.

    Matches the pre-#100 init layout expected by most unit tests.
    """
    init = init_project(
        target,
        project_type="configuration",
        name=name,
        ide_target=ide_target,
        force=force,
    )
    if init.status != "ok":
        return init
    add = add_configuration(
        target,
        config_id="main",
        name=name,
        source_path="src/cf",
        force=force,
    )
    add.created = [*init.created, *add.created]
    return add
