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
from core.publish.paths import DEFAULT_HTTP_PORT, DEFAULT_WEBINST_PORT

SUPPORTED_BACKENDS = frozenset({"ibsrv", "webinst"})
DEFAULT_BACKEND = "webinst"


@dataclass(frozen=True)
class ResolvedPublishProfile:
    """Selected publish profile + runtime reference."""

    profile_id: str
    backend: str
    runtime_id: str
    port: int
    config_rel: str | None
    name: str
    server: str = "apache24"
    wsdir: str | None = None
    dir_rel: str | None = None
    confpath_rel: str | None = None


def default_profile_id_for_backend(backend: str) -> str:
    """Canonical profile id for ``--backend`` ensure (``local-ibsrv`` / ``local-webinst``)."""
    return f"local-{backend}"


def build_default_profile_entry(
    backend: str,
    *,
    runtime_id: str,
    profile_id: str,
) -> dict[str, Any]:
    """Body for a newly ensured publish profile."""
    if backend == "ibsrv":
        return {
            "backend": "ibsrv",
            "port": DEFAULT_HTTP_PORT,
            "runtime": runtime_id,
            "config": f".1c-dev/publish/{profile_id}/ibsrv.yaml",
        }
    return {
        "backend": "webinst",
        "port": DEFAULT_WEBINST_PORT,
        "runtime": runtime_id,
    }


def _normalize_backend(raw: str | None) -> tuple[str | None, list[Diagnostic]]:
    if raw is None:
        return None, []
    backend = raw.strip()
    if not backend:
        return None, []
    if backend not in SUPPORTED_BACKENDS:
        return None, [
            error(
                f"Неподдерживаемый publish backend={backend!r}",
                code=CODE_BACKEND_UNSUPPORTED,
                source="publish",
                suggestion="Допустимо: ibsrv, webinst.",
            )
        ]
    return backend, []


def _find_profile_id_by_backend(publish: dict[str, Any], backend: str) -> str | None:
    profiles = publish.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return None

    default = publish.get("default")
    if isinstance(default, str) and default.strip():
        default_id = default.strip()
        raw = profiles.get(default_id)
        if isinstance(raw, dict) and str(raw.get("backend") or "").strip() == backend:
            return default_id

    matches = [
        str(pid)
        for pid, raw in profiles.items()
        if isinstance(raw, dict) and str(raw.get("backend") or "").strip() == backend
    ]
    if not matches:
        return None
    canonical = default_profile_id_for_backend(backend)
    if canonical in matches:
        return canonical
    return sorted(matches)[0]


def _default_runtime_id(data: dict[str, Any]) -> tuple[str | None, list[Diagnostic]]:
    from core.project.resolve import resolve_config_runtime

    target, diags = resolve_config_runtime(data, require_runtime=True)
    if target is None or not target.runtime_id:
        return None, list(diags) or [
            error(
                "Не удалось выбрать runtime для publish-профиля",
                code=CODE_PROJECT,
                source="publish",
                suggestion="Добавьте runtimes[] с default: true или укажите --profile.",
            )
        ]
    return target.runtime_id, []


def _ensure_profile_entry(
    data: dict[str, Any],
    *,
    backend: str,
    runtime_id: str,
) -> str:
    """Insert canonical ``local-<backend>`` profile; mutate ``data``. Return profile id."""
    profile_id = default_profile_id_for_backend(backend)
    entry = build_default_profile_entry(backend, runtime_id=runtime_id, profile_id=profile_id)
    publish = data.get("publish")
    if not isinstance(publish, dict):
        data["publish"] = {
            "default": profile_id,
            "profiles": {profile_id: entry},
        }
        return profile_id

    profiles = publish.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        publish["profiles"] = profiles
    profiles[profile_id] = entry
    default = publish.get("default")
    if not (isinstance(default, str) and default.strip()):
        publish["default"] = profile_id
    return profile_id


def resolve_or_ensure_publish_profile(
    data: dict[str, Any],
    *,
    profile_id: str | None = None,
    backend: str | None = None,
    ensure: bool = False,
) -> tuple[ResolvedPublishProfile | None, list[Diagnostic], bool]:
    """
    Resolve publish profile; optionally select/ensure by ``backend``.

    - ``profile_id`` only → classic resolve.
    - ``backend`` only → prefer ``publish.default`` if it matches, else any matching
      profile, else (when ``ensure``) create ``local-<backend>``.
    - both → resolve profile; fail if backends mismatch.
    """
    backend_norm, backend_diags = _normalize_backend(backend)
    if backend_diags:
        return None, backend_diags, False

    selected_id = profile_id.strip() if isinstance(profile_id, str) and profile_id.strip() else None

    if selected_id is not None:
        profile, diags = resolve_publish_profile(data, profile_id=selected_id)
        if profile is None:
            return None, diags, False
        if backend_norm is not None and profile.backend != backend_norm:
            return (
                None,
                [
                    error(
                        (
                            f"Профиль {selected_id!r} имеет backend={profile.backend!r}, "
                            f"а запрошен {backend_norm!r}"
                        ),
                        code=CODE_BACKEND_UNSUPPORTED,
                        source="publish",
                        suggestion=(
                            "Укажите --profile без --backend "
                            "или согласуйте backend профиля."
                        ),
                    )
                ],
                False,
            )
        return profile, [], False

    if backend_norm is not None:
        publish = data.get("publish")
        if isinstance(publish, dict):
            found = _find_profile_id_by_backend(publish, backend_norm)
            if found is not None:
                profile, diags = resolve_publish_profile(data, profile_id=found)
                return profile, diags, False

        if not ensure:
            return (
                None,
                [
                    error(
                        f"Нет publish-профиля с backend={backend_norm!r}",
                        code=CODE_PROFILE_UNKNOWN,
                        source="publish",
                        suggestion=(
                            f"Выполните 1c-dev publish up --backend {backend_norm} "
                            f"(создаст {default_profile_id_for_backend(backend_norm)}) "
                            "или добавьте профиль в project.yaml."
                        ),
                    )
                ],
                False,
            )

        runtime_id, rt_diags = _default_runtime_id(data)
        if runtime_id is None:
            return None, rt_diags, False

        new_id = _ensure_profile_entry(data, backend=backend_norm, runtime_id=runtime_id)
        profile, diags = resolve_publish_profile(data, profile_id=new_id)
        return profile, diags, True

    profile, diags = resolve_publish_profile(data, profile_id=None)
    return profile, diags, False


def resolve_publish_profile(
    data: dict[str, Any],
    *,
    profile_id: str | None = None,
) -> tuple[ResolvedPublishProfile | None, list[Diagnostic]]:
    """
    Resolve ``publish.profiles`` entry.

    Without ``profile_id`` uses ``publish.default``. Supported backends:
    ``ibsrv`` and ``webinst``.
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
                    "(backend: ibsrv|webinst, runtime: <id>) "
                    "или 1c-dev publish up --backend ibsrv|webinst."
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
                suggestion="Добавьте хотя бы один профиль с backend: ibsrv или webinst.",
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
    if backend not in SUPPORTED_BACKENDS:
        return None, [
            error(
                f"Неподдерживаемый publish backend={backend!r}",
                code=CODE_BACKEND_UNSUPPORTED,
                source="publish",
                suggestion="Допустимо: ibsrv, webinst.",
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

    default_port = DEFAULT_WEBINST_PORT if backend == "webinst" else DEFAULT_HTTP_PORT
    port_raw = raw.get("port", default_port)
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

    server_raw = raw.get("server")
    server = (
        server_raw.strip()
        if isinstance(server_raw, str) and server_raw.strip()
        else "apache24"
    )

    wsdir_raw = raw.get("wsdir")
    wsdir = (
        wsdir_raw.strip()
        if isinstance(wsdir_raw, str) and wsdir_raw.strip()
        else selected
    )

    dir_rel: str | None = None
    dir_raw = raw.get("dir")
    if isinstance(dir_raw, str) and dir_raw.strip():
        dir_rel = dir_raw.strip()

    confpath_rel: str | None = None
    conf_raw = raw.get("confpath")
    if isinstance(conf_raw, str) and conf_raw.strip():
        confpath_rel = conf_raw.strip()

    return (
        ResolvedPublishProfile(
            profile_id=selected,
            backend=backend,
            runtime_id=runtime_id.strip(),
            port=port,
            config_rel=config_rel,
            name=name,
            server=server,
            wsdir=wsdir,
            dir_rel=dir_rel,
            confpath_rel=confpath_rel,
        ),
        [],
    )
