"""Clean user cache and optionally uninstall uv tool package."""

from __future__ import annotations

import shutil
import subprocess

from core.diagnostics import Diagnostic, error, info, warning
from core.toolchain.cache import cache_root
from core.toolchain.result import OverallStatus, UninstallResult

UV_PACKAGE_NAME = "1c-dev"


def clean_tools_cache(
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> UninstallResult:
    """Remove the user cache root (tools + docs). Does not touch uv tool package."""
    root = cache_root(env=env, platform=platform)
    diagnostics: list[Diagnostic] = []
    removed = False
    if root.exists():
        try:
            shutil.rmtree(root)
            removed = True
            diagnostics.append(
                info(
                    f"Удалён cache: {root}",
                    code="1CT040",
                    source="toolchain",
                )
            )
        except OSError as exc:
            diagnostics.append(
                error(
                    f"Не удалось удалить cache {root}: {exc}",
                    code="1CT041",
                    source="toolchain",
                )
            )
            return UninstallResult(
                status="error",
                cache_removed=False,
                package_uninstalled=None,
                diagnostics=diagnostics,
            )
    else:
        diagnostics.append(
            info(
                f"Cache уже отсутствует: {root}",
                code="1CT040",
                source="toolchain",
            )
        )
    return UninstallResult(
        status="ok",
        cache_removed=removed or not root.exists(),
        package_uninstalled=None,
        diagnostics=diagnostics,
    )


def _find_uv() -> str | None:
    return shutil.which("uv") or shutil.which("uv.exe")


def uninstall_uv_package(
    *,
    package: str = UV_PACKAGE_NAME,
) -> tuple[bool | None, list[Diagnostic]]:
    """Run `uv tool uninstall <package>`. Returns (uninstalled, diagnostics)."""
    diagnostics: list[Diagnostic] = []
    uv = _find_uv()
    if not uv:
        diagnostics.append(
            warning(
                "uv не найден — пакет CLI не снят (cache уже мог быть очищен)",
                code="1CT042",
                source="toolchain",
                suggestion="Установите uv или выполните: uv tool uninstall 1c-dev",
            )
        )
        return False, diagnostics

    proc = subprocess.run(
        [uv, "tool", "uninstall", package],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        diagnostics.append(
            info(
                f"Пакет снят: uv tool uninstall {package}",
                code="1CT043",
                source="toolchain",
            )
        )
        return True, diagnostics

    # Already missing is ok-ish
    combined = ((proc.stderr or "") + (proc.stdout or "")).lower()
    if "not installed" in combined or "no tool" in combined or "could not find" in combined:
        diagnostics.append(
            info(
                f"Пакет {package} уже не установлен через uv tool",
                code="1CT043",
                source="toolchain",
            )
        )
        return False, diagnostics

    diagnostics.append(
        warning(
            f"uv tool uninstall {package} завершился с кодом {proc.returncode}",
            code="1CT044",
            source="toolchain",
            suggestion=(proc.stderr or proc.stdout or "").strip()[:500]
            or "Проверьте вывод uv tool list",
        )
    )
    return False, diagnostics


def uninstall_tools(
    *,
    keep_package: bool = False,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> UninstallResult:
    """Remove cache, then optionally `uv tool uninstall 1c-dev`."""
    cache_result = clean_tools_cache(env=env, platform=platform)
    diagnostics = list(cache_result.diagnostics)

    if keep_package:
        status = cache_result.status
        return UninstallResult(
            status=status,
            cache_removed=cache_result.cache_removed,
            package_uninstalled=None,
            diagnostics=diagnostics,
        )

    uninstalled, pkg_diags = uninstall_uv_package()
    diagnostics.extend(pkg_diags)

    if cache_result.status == "error":
        overall: OverallStatus = "error"
    elif uninstalled is False and any(d.get("severity") == "warning" for d in pkg_diags):
        # uv missing or uninstall failed — degraded if cache gone
        overall = (
            "degraded"
            if cache_result.cache_removed
            or not cache_root(env=env, platform=platform).exists()
            else "error"
        )
    else:
        overall = "ok"

    return UninstallResult(
        status=overall,
        cache_removed=cache_result.cache_removed,
        package_uninstalled=uninstalled,
        diagnostics=diagnostics,
    )
