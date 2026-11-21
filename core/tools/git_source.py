"""Clone git sources for external tool recipes (ADR-033 Этап 3)."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from core.diagnostics import Diagnostic, error, info
from core.tools.catalog import ToolRecipe

ProgressCb = Callable[[str], None] | None


def git_available() -> bool:
    return shutil.which("git") is not None


def clone_recipe_source(
    recipe: ToolRecipe,
    tool_dir: Path,
    *,
    progress: ProgressCb = None,
) -> tuple[bool, list[Diagnostic]]:
    """Clone ``source.url`` into ``tool_dir / source.dest`` at ``source.ref``."""
    source = recipe.raw.get("source")
    if not isinstance(source, dict) or str(source.get("type") or "") != "git":
        return True, []

    if not git_available():
        return False, [
            error(
                "git не найден в PATH (нужен для clone upstream)",
                code="1CX003",
                source="tools",
                suggestion="Установите git",
            )
        ]

    url = str(source.get("url") or "").strip()
    ref = str(source.get("ref") or "HEAD").strip()
    dest_name = str(source.get("dest") or "upstream").strip() or "upstream"
    if not url:
        return False, [
            error(
                "source.url пуст в tool.yaml",
                code="1CX007",
                source="tools",
            )
        ]

    dest = tool_dir / dest_name
    if dest.is_dir() and (dest / ".git").is_dir():
        if progress:
            progress(f"git fetch/checkout {ref} в {dest}…")
        fetch = subprocess.run(
            ["git", "-C", str(dest), "fetch", "--depth", "1", "origin", ref],
            capture_output=True,
            text=True,
            check=False,
        )
        if fetch.returncode != 0:
            # Shallow fetch by ref may fail for commit SHA; try unshallow fetch.
            fetch2 = subprocess.run(
                ["git", "-C", str(dest), "fetch", "--depth", "1", "origin"],
                capture_output=True,
                text=True,
                check=False,
            )
            if fetch2.returncode != 0:
                detail = (fetch.stderr or fetch2.stderr or "").strip()[:400]
                return False, [
                    error(
                        f"git fetch failed: {detail or fetch.returncode}",
                        code="1CX006",
                        source="tools",
                    )
                ]
        checkout = subprocess.run(
            ["git", "-C", str(dest), "checkout", "--force", ref],
            capture_output=True,
            text=True,
            check=False,
        )
        if checkout.returncode != 0:
            detail = (checkout.stderr or "").strip()[:400]
            return False, [
                error(
                    f"git checkout {ref} failed: {detail or checkout.returncode}",
                    code="1CX006",
                    source="tools",
                )
            ]
        return True, [
            info(f"upstream обновлён ({ref})", code="1CX000", source="tools"),
        ]

    if dest.exists():
        shutil.rmtree(dest)

    if progress:
        progress(f"git clone {url}@{ref} → {dest}…")
    # Prefer shallow clone of exact commit via fetch after init.
    dest.mkdir(parents=True, exist_ok=True)
    steps = [
        ["git", "-C", str(dest), "init"],
        ["git", "-C", str(dest), "remote", "add", "origin", url],
        ["git", "-C", str(dest), "fetch", "--depth", "1", "origin", ref],
        ["git", "-C", str(dest), "checkout", "FETCH_HEAD"],
    ]
    for cmd in steps:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            # Fallback: full clone (some remotes reject commit-ish fetch).
            if dest.exists():
                shutil.rmtree(dest)
            if progress:
                progress(f"git clone (full) {url}…")
            clone = subprocess.run(
                ["git", "clone", "--recurse-submodules", url, str(dest)],
                capture_output=True,
                text=True,
                check=False,
            )
            if clone.returncode != 0:
                detail = (completed.stderr or clone.stderr or "").strip()[:500]
                return False, [
                    error(
                        f"git clone failed: {detail or clone.returncode}",
                        code="1CX006",
                        source="tools",
                        suggestion="Проверьте сеть и доступ к GitHub",
                    )
                ]
            checkout = subprocess.run(
                ["git", "-C", str(dest), "checkout", "--force", ref],
                capture_output=True,
                text=True,
                check=False,
            )
            if checkout.returncode != 0:
                detail = (checkout.stderr or "").strip()[:400]
                return False, [
                    error(
                        f"git checkout {ref} failed: {detail or checkout.returncode}",
                        code="1CX006",
                        source="tools",
                    )
                ]
            break
    return True, [
        info(f"upstream склонирован ({ref})", code="1CX000", source="tools"),
    ]
