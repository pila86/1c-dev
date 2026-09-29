"""Resolve publish profile from schema \"2\" manifest (ADR-025)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.diagnostics import Diagnostic, error
from core.publish.constants import (
    CODE_BACKEND_UNSUPPORTED,
    CODE_PROFILE_UNKNOWN,
    CODE_PROJECT,
)
from core.publish.paths import DEFAULT_HTTP_PORT


@dataclass(frozen=True)
class ResolvedPublishProfile:
    """Selected publish profile + runtime reference."""

    profile_id: str
    backend: str
    runtime_id: str
    port: int
    config_rel: str | None
    name: str


def resolve_publish_profile(
    data: dict[str, Any],
    *,
    profile_id: str | None = None,
) -> tuple[ResolvedPublishProfile | None, list[Diagnostic]]:
    """
    Resolve ``publish.profiles`` entry.

    Without ``profile_id`` uses ``publish.default``. Only ``ibsrv`` backend is
    supported in #89; ``webinst`` returns an explicit error.
    """
    publish = data.get("publish")
    if not isinstance(publish, dict):
        return None, [
            error(
                "В манифесте нет секции publish",
                code=CODE_PROJECT,
                source="publish",
                suggestion=(
                    "Добавьте publish.default и publish.profiles "
                    "(backend: ibsrv, runtime: <id>)."
                ),
            )
        ]

    profiles = publish.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return None, [
            error(
                "publish.profiles пуст",
                code=CODE_PROJECT,
                source="publish",
                suggestion="Добавьте хотя бы один профиль с backend: ibsrv.",
            )
        ]

    selected = profile_id
    if selected is None:
        default = publish.get("default")
        if isinstance(default, str) and default.strip():
            selected = default.strip()
        elif len(profiles) == 1:
            selected = next(iter(profiles))
        else:
            return None, [
                error(
                    "Не указан publish profile и нет publish.default",
                    code=CODE_PROFILE_UNKNOWN,
                    source="publish",
                    suggestion=f"Доступные профили: {', '.join(sorted(profiles))}",
                )
            ]

    raw = profiles.get(selected)
    if not isinstance(raw, dict):
        return None, [
            error(
                f"Неизвестный publish profile id={selected!r}",
                code=CODE_PROFILE_UNKNOWN,
                source="publish",
                suggestion=f"Доступные профили: {', '.join(sorted(str(k) for k in profiles))}",
            )
        ]

    backend = str(raw.get("backend") or "").strip()
    if backend == "webinst":
        return None, [
            error(
                "Backend webinst ещё не реализован (issue #94)",
                code=CODE_BACKEND_UNSUPPORTED,
                source="publish",
                suggestion="Используйте backend: ibsrv или дождитесь #94.",
            )
        ]
    if backend != "ibsrv":
        return None, [
            error(
                f"Неподдерживаемый publish backend={backend!r}",
                code=CODE_BACKEND_UNSUPPORTED,
                source="publish",
                suggestion="Допустимо: ibsrv (MVP).",
            )
        ]

    runtime_id = raw.get("runtime")
    if not isinstance(runtime_id, str) or not runtime_id.strip():
        return None, [
            error(
                f"publish.profiles.{selected}: нет runtime",
                code=CODE_PROJECT,
                source="publish",
            )
        ]

    port_raw = raw.get("port", DEFAULT_HTTP_PORT)
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        return None, [
            error(
                f"publish.profiles.{selected}.port: ожидается целое число",
                code=CODE_PROJECT,
                source="publish",
            )
        ]
    if port < 1:
        return None, [
            error(
                f"publish.profiles.{selected}.port: должен быть ≥ 1",
                code=CODE_PROJECT,
                source="publish",
            )
        ]

    config_rel: str | None = None
    config_raw = raw.get("config")
    if isinstance(config_raw, str) and config_raw.strip():
        config_rel = config_raw.strip()

    name_raw = raw.get("name")
    name = (
        name_raw.strip()
        if isinstance(name_raw, str) and name_raw.strip()
        else selected
    )

    return (
        ResolvedPublishProfile(
            profile_id=selected,
            backend=backend,
            runtime_id=runtime_id.strip(),
            port=port,
            config_rel=config_rel,
            name=name,
        ),
        [],
    )
