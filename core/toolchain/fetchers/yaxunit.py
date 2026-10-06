"""Download YAxUnit runner extension (.cfe) into the user tools cache (ADR-029 §7a)."""

from __future__ import annotations

import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from core.diagnostics import Diagnostic, warning
from core.toolchain.fetchers import install_jar_pair, pin_artifact_name, sha256_file
from core.toolchain.manifest import ComponentSpec
from core.toolchain.progress import ProgressFn, noop_progress

DEFAULT_YAXUNIT_PIN = "25.12"
DEFAULT_YAXUNIT_URL = (
    "https://github.com/bia-technologies/yaxunit/releases/download/"
    "25.12/YAxUnit-25.12.cfe"
)


def fetch_yaxunit(
    spec: ComponentSpec,
    tools_dir: Path,
    *,
    env: dict[str, str] | None = None,
    progress: ProgressFn | None = None,
    quiet: bool = True,
) -> tuple[Path | None, list[Diagnostic]]:
    """Idempotently download YAxUnit.cfe. Failure is soft (warning) for overall sync."""
    del env, quiet  # reserved for future proxy/env overrides
    report = progress or noop_progress
    diagnostics: list[Diagnostic] = []
    pin = spec.pin or DEFAULT_YAXUNIT_PIN
    artifact = spec.artifact
    pinned = tools_dir / pin_artifact_name(artifact, pin)
    stable = tools_dir / artifact

    if pinned.is_file():
        tools_dir.mkdir(parents=True, exist_ok=True)
        if spec.sha256 and sha256_file(pinned).lower() != spec.sha256.lower():
            diagnostics.append(
                warning(
                    f"sha256 mismatch for {artifact}: expected {spec.sha256}",
                    code="1CT021",
                    source="toolchain",
                    suggestion="Перекачиваю артефакт; при повторе обновите pin в манифесте.",
                )
            )
            pinned.unlink(missing_ok=True)
            stable.unlink(missing_ok=True)
        else:
            shutil.copy2(pinned, stable)
            report(f"→ {spec.id}: cache hit")
            return stable.resolve(), diagnostics

    url = str(spec.source.get("url") or DEFAULT_YAXUNIT_URL)
    tools_dir.mkdir(parents=True, exist_ok=True)
    report(f"→ {spec.id}: download…")

    try:
        with tempfile.NamedTemporaryFile(
            prefix="yaxunit-",
            suffix=".cfe",
            delete=False,
            dir=str(tools_dir),
        ) as tmp:
            tmp_path = Path(tmp.name)
        try:
            urllib.request.urlretrieve(url, tmp_path)  # noqa: S310 — pinned release URL
            if spec.sha256 and sha256_file(tmp_path).lower() != spec.sha256.lower():
                diagnostics.append(
                    warning(
                        f"sha256 mismatch after download of {artifact}",
                        code="1CT021",
                        source="toolchain",
                        suggestion="Проверьте pin/url/sha256 в toolchain/manifest.yaml.",
                    )
                )
                return None, diagnostics
            stable_path = install_jar_pair(
                built=tmp_path,
                tools_dir=tools_dir,
                artifact=artifact,
                pin=pin,
            )
            return stable_path, diagnostics
        finally:
            tmp_path.unlink(missing_ok=True)
    except (urllib.error.URLError, OSError) as exc:
        diagnostics.append(
            warning(
                f"Не удалось скачать YAxUnit.cfe: {exc}",
                code="1CT022",
                source="toolchain",
                suggestion="Проверьте сеть или задайте ONEC_YAXUNIT_CFE=/path/to/YAxUnit.cfe.",
            )
        )
        return None, diagnostics
