"""Download github-release assets for external tool install (ADR-033 Этап 7)."""

from __future__ import annotations

import shutil
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from core.diagnostics import Diagnostic, error, info
from core.toolchain.fetchers import sha256_file
from core.tools.catalog import ToolRecipe

ProgressCb = Callable[[str], None] | None


def download_github_release_asset(
    recipe: ToolRecipe,
    tool_dir: Path,
    *,
    progress: ProgressCb = None,
) -> tuple[bool, list[Diagnostic]]:
    """Download ``source.url`` into ``source.dest`` under tool_dir (idempotent)."""
    diags: list[Diagnostic] = []
    source = recipe.raw.get("source")
    if not isinstance(source, dict) or str(source.get("type") or "") != "github-release":
        return True, diags

    url = str(source.get("url") or "")
    dest_rel = str(source.get("dest") or source.get("asset") or "")
    expected_sha = str(source.get("sha256") or "")
    if not url or not dest_rel:
        diags.append(
            error(
                "source.url / source.dest обязательны для github-release",
                code="1CX007",
                source="tools",
            )
        )
        return False, diags

    dest = tool_dir / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.is_file() and expected_sha:
        digest = sha256_file(dest)
        if digest.lower() == expected_sha.lower():
            if progress:
                progress(f"→ {recipe.id}: jar cache hit ({dest.name})")
            diags.append(
                info(f"asset уже на месте: {dest}", code="1CX000", source="tools")
            )
            return True, diags
        dest.unlink(missing_ok=True)
    elif dest.is_file() and not expected_sha:
        diags.append(
            info(f"asset уже на месте: {dest}", code="1CX000", source="tools")
        )
        return True, diags

    if progress:
        progress(f"→ {recipe.id}: download {url.rsplit('/', 1)[-1]}…")

    try:
        with tempfile.NamedTemporaryFile(
            prefix=f"{recipe.id}-",
            suffix=".download",
            delete=False,
            dir=str(dest.parent),
        ) as tmp:
            tmp_path = Path(tmp.name)
        try:
            urllib.request.urlretrieve(url, tmp_path)  # noqa: S310 — pinned release URL
            if expected_sha:
                digest = sha256_file(tmp_path)
                if digest.lower() != expected_sha.lower():
                    diags.append(
                        error(
                            (
                                f"sha256 mismatch for {dest.name}: "
                                f"expected {expected_sha}, got {digest}"
                            ),
                            code="1CX006",
                            source="tools",
                            suggestion="Проверьте pin/url/sha256 в catalog recipe",
                        )
                    )
                    tmp_path.unlink(missing_ok=True)
                    return False, diags
            shutil.move(str(tmp_path), str(dest))
        finally:
            tmp_path.unlink(missing_ok=True)
    except (urllib.error.URLError, OSError) as exc:
        diags.append(
            error(
                f"не удалось скачать {url}: {exc}",
                code="1CX006",
                source="tools",
                suggestion="Проверьте сеть или задайте ONEC_BSLLS_JAR",
            )
        )
        return False, diags

    diags.append(info(f"скачан {dest}", code="1CX000", source="tools"))
    return True, diags
