"""Resolve ``configurations[]`` / ``runtimes[]`` by ``--config`` / ``--runtime`` (ADR-023/026)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.diagnostics import Diagnostic, error
from core.project.constants import (
    CODE_CONFIG_AMBIGUOUS,
    CODE_CONFIG_UNKNOWN,
    CODE_RUNTIME_AMBIGUOUS,
    CODE_RUNTIME_CONFIG_MISMATCH,
    CODE_RUNTIME_UNKNOWN,
    DEFAULT_CONFIG_ID,
    LEGACY_RUNTIME_DIR_NAME,
)


@dataclass(frozen=True)
class ResolvedTarget:
    """Selected configuration and (optionally) runtime from a project manifest."""

    configuration: dict[str, Any]
    runtime: dict[str, Any] | None
    config_id: str
    runtime_id: str | None
    source_rel: str
    source_format: str | None
    runtime_rel: str | None
    runtime_type: str | None


def _source_from_conf(conf: dict[str, Any]) -> tuple[str, str | None]:
    source = conf.get("source")
    if not isinstance(source, dict):
        return "src/cf", None
    path = source.get("path")
    rel = path if isinstance(path, str) and path else "src/cf"
    fmt = source.get("format")
    return rel, (str(fmt) if fmt is not None else None)


def _runtime_fields(rt: dict[str, Any]) -> tuple[str, str]:
    path = rt.get("path")
    rel = path if isinstance(path, str) and path else f"{LEGACY_RUNTIME_DIR_NAME}/ib"
    raw_type = rt.get("type")
    rtype = raw_type if isinstance(raw_type, str) and raw_type else "file"
    return rel, rtype


def _list_dicts(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _id_of(item: dict[str, Any]) -> str | None:
    raw = item.get("id")
    return raw if isinstance(raw, str) and raw else None


def _find_by_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    for item in items:
        if _id_of(item) == item_id:
            return item
    return None


def _runtimes_for_config(
    runtimes: list[dict[str, Any]],
    config_id: str,
) -> list[dict[str, Any]]:
    return [rt for rt in runtimes if rt.get("configuration") == config_id]


def _known_ids(items: list[dict[str, Any]]) -> str:
    return ", ".join(sorted(i for i in (_id_of(x) for x in items) if i)) or "—"


def _pick_default_configuration(
    configurations: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    marked = [c for c in configurations if c.get("default") is True]
    if len(marked) > 1:
        return None, [
            error(
                "Несколько configurations с default: true",
                code=CODE_CONFIG_AMBIGUOUS,
                source="project",
                suggestion="Оставьте ровно один default: true или укажите --config",
            )
        ]
    if len(marked) == 1:
        return marked[0], []
    if len(configurations) == 1:
        return configurations[0], []
    return None, [
        error(
            "Несколько configurations без default: true — укажите --config",
            code=CODE_CONFIG_AMBIGUOUS,
            source="project",
            suggestion=f"Доступные configuration id: {_known_ids(configurations)}",
        )
    ]


def _pick_runtime_for_config(
    related: list[dict[str, Any]],
    *,
    conf_id: str,
) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    if len(related) == 1:
        return related[0], []
    if len(related) == 0:
        return None, [
            error(
                f"Нет runtime для configuration id={conf_id!r}",
                code=CODE_RUNTIME_UNKNOWN,
                source="project",
                suggestion=f"Добавьте элемент в runtimes[] с configuration: {conf_id}",
            )
        ]
    defaults = [rt for rt in related if rt.get("default") is True]
    if len(defaults) == 1:
        return defaults[0], []
    return None, [
        error(
            f"У configuration id={conf_id!r} несколько runtime — укажите --runtime",
            code=CODE_RUNTIME_AMBIGUOUS,
            source="project",
            suggestion=f"Доступные runtime id: {_known_ids(related)}",
        )
    ]


def _pick_global_default_runtime(
    runtimes: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    defaults = [rt for rt in runtimes if rt.get("default") is True]
    if len(defaults) == 1:
        return defaults[0], []
    if len(defaults) > 1:
        return None, [
            error(
                "Несколько runtimes с default: true",
                code=CODE_RUNTIME_AMBIGUOUS,
                source="project",
                suggestion="Оставьте ровно один default: true или укажите --runtime",
            )
        ]
    if len(runtimes) == 1:
        return runtimes[0], []
    return None, [
        error(
            "Не удалось выбрать runtime: нет default: true — укажите --runtime",
            code=CODE_RUNTIME_AMBIGUOUS,
            source="project",
            suggestion=f"Доступные runtime id: {_known_ids(runtimes)}",
        )
    ]


def _target_from(
    conf: dict[str, Any],
    rt: dict[str, Any] | None,
) -> tuple[ResolvedTarget | None, list[Diagnostic]]:
    conf_id = _id_of(conf)
    if conf_id is None:
        return None, [
            error(
                "У выбранной configuration отсутствует id",
                code=CODE_CONFIG_UNKNOWN,
                source="project",
            )
        ]
    source_rel, source_format = _source_from_conf(conf)
    if rt is None:
        return (
            ResolvedTarget(
                configuration=conf,
                runtime=None,
                config_id=conf_id,
                runtime_id=None,
                source_rel=source_rel,
                source_format=source_format,
                runtime_rel=None,
                runtime_type=None,
            ),
            [],
        )
    rt_id = _id_of(rt)
    if rt_id is None:
        return None, [
            error(
                "У выбранного runtime отсутствует id",
                code=CODE_RUNTIME_UNKNOWN,
                source="project",
            )
        ]
    rt_conf = rt.get("configuration")
    if rt_conf != conf_id:
        return None, [
            error(
                (
                    f"runtime id={rt_id!r} относится к configuration {rt_conf!r}, "
                    f"а не к {conf_id!r}"
                ),
                code=CODE_RUNTIME_CONFIG_MISMATCH,
                source="project",
                suggestion="Укажите согласованные --config и --runtime",
            )
        ]
    runtime_rel, runtime_type = _runtime_fields(rt)
    return (
        ResolvedTarget(
            configuration=conf,
            runtime=rt,
            config_id=conf_id,
            runtime_id=rt_id,
            source_rel=source_rel,
            source_format=source_format,
            runtime_rel=runtime_rel,
            runtime_type=runtime_type,
        ),
        [],
    )


def _resolve_schema1(
    data: dict[str, Any],
    *,
    config_id: str | None,
    runtime_id: str | None,
    require_runtime: bool,
) -> tuple[ResolvedTarget | None, list[Diagnostic]]:
    """Single source/runtime layout (schema \"1\")."""
    syn_config_id = DEFAULT_CONFIG_ID
    syn_runtime_id = "default"
    if config_id is not None and config_id not in {syn_config_id, "default"}:
        return None, [
            error(
                f"Неизвестная configuration id={config_id!r} "
                f"(schema \"1\" поддерживает только {syn_config_id!r})",
                code=CODE_CONFIG_UNKNOWN,
                source="project",
                suggestion="Уберите --config или укажите schema \"2\" с configurations[]",
            )
        ]
    if runtime_id is not None and runtime_id not in {syn_runtime_id, syn_config_id}:
        return None, [
            error(
                f"Неизвестный runtime id={runtime_id!r} "
                f"(schema \"1\" поддерживает только {syn_runtime_id!r})",
                code=CODE_RUNTIME_UNKNOWN,
                source="project",
                suggestion="Уберите --runtime или укажите schema \"2\" с runtimes[]",
            )
        ]

    source_raw = data.get("source")
    source: dict[str, Any] = source_raw if isinstance(source_raw, dict) else {}
    source_rel = str(source.get("path") or "src/cf")
    fmt = source.get("format")
    source_format = str(fmt) if fmt is not None else None

    runtime_raw = data.get("runtime")
    runtime: dict[str, Any] = runtime_raw if isinstance(runtime_raw, dict) else {}
    runtime_rel = str(runtime.get("path") or f"{LEGACY_RUNTIME_DIR_NAME}/ib")
    runtime_type = str(runtime.get("type") or "file")

    conf = {
        "id": syn_config_id,
        "type": "configuration",
        "default": True,
        "source": {"format": source_format or "xml", "path": source_rel},
    }
    rt = {
        "id": syn_runtime_id,
        "configuration": syn_config_id,
        "type": runtime_type,
        "path": runtime_rel,
        "default": True,
    }
    if not require_runtime and runtime_id is None:
        return _target_from(conf, None)
    return _target_from(conf, rt)


def resolve_config_runtime(
    data: dict[str, Any],
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    require_runtime: bool = True,
) -> tuple[ResolvedTarget | None, list[Diagnostic]]:
    """
    Resolve configuration + runtime from manifest data.

    Rules (schema \"2\", ADR-023 / ADR-026):
    - без флагов → global ``default: true`` runtime и его configuration;
    - ``--runtime`` → элемент ``runtimes[]``, configuration из связи;
    - ``--config`` → configuration; runtime = единственная ИБ / global default
      этой configuration, иначе ошибка неоднозначности;
    - оба флага → проверка, что runtime.configuration == config id.

    ``require_runtime=False`` (metadata): runtime резолвится только при
    ``runtime_id``; иначе поля runtime остаются ``None``.
    """
    if str(data.get("schema")) != "2":
        return _resolve_schema1(
            data,
            config_id=config_id,
            runtime_id=runtime_id,
            require_runtime=require_runtime,
        )

    configurations = _list_dicts(data.get("configurations"))
    runtimes = _list_dicts(data.get("runtimes"))

    if not configurations:
        return None, [
            error(
                "В манифесте нет configurations[]",
                code=CODE_CONFIG_UNKNOWN,
                source="project",
            )
        ]

    selected_rt: dict[str, Any] | None = None
    selected_conf: dict[str, Any] | None = None

    if runtime_id is not None:
        selected_rt = _find_by_id(runtimes, runtime_id)
        if selected_rt is None:
            return None, [
                error(
                    f"Неизвестный runtime id={runtime_id!r}",
                    code=CODE_RUNTIME_UNKNOWN,
                    source="project",
                    suggestion=f"Доступные runtime id: {_known_ids(runtimes)}",
                )
            ]

    if config_id is not None:
        selected_conf = _find_by_id(configurations, config_id)
        if selected_conf is None:
            return None, [
                error(
                    f"Неизвестная configuration id={config_id!r}",
                    code=CODE_CONFIG_UNKNOWN,
                    source="project",
                    suggestion=f"Доступные configuration id: {_known_ids(configurations)}",
                )
            ]

    if selected_rt is not None and selected_conf is not None:
        if selected_rt.get("configuration") != _id_of(selected_conf):
            return None, [
                error(
                    (
                        f"runtime id={runtime_id!r} относится к configuration "
                        f"{selected_rt.get('configuration')!r}, а не к {config_id!r}"
                    ),
                    code=CODE_RUNTIME_CONFIG_MISMATCH,
                    source="project",
                    suggestion="Укажите --runtime, связанный с выбранным --config",
                )
            ]

    if selected_rt is not None and selected_conf is None:
        rt_conf_id = selected_rt.get("configuration")
        if not isinstance(rt_conf_id, str) or not rt_conf_id:
            return None, [
                error(
                    f"У runtime id={runtime_id!r} нет поля configuration",
                    code=CODE_RUNTIME_CONFIG_MISMATCH,
                    source="project",
                )
            ]
        selected_conf = _find_by_id(configurations, rt_conf_id)
        if selected_conf is None:
            return None, [
                error(
                    (
                        f"runtime id={runtime_id!r} ссылается на неизвестную "
                        f"configuration {rt_conf_id!r}"
                    ),
                    code=CODE_RUNTIME_CONFIG_MISMATCH,
                    source="project",
                )
            ]

    if selected_conf is None:
        # No --config / --runtime: for source-only use default configuration;
        # for full resolve use global default runtime → its configuration.
        if not require_runtime:
            selected_conf, diags = _pick_default_configuration(configurations)
            if selected_conf is None:
                return None, diags
            return _target_from(selected_conf, None)

        selected_rt, diags = _pick_global_default_runtime(runtimes)
        if selected_rt is None:
            return None, diags
        rt_conf_id = selected_rt.get("configuration")
        if not isinstance(rt_conf_id, str) or not rt_conf_id:
            return None, [
                error(
                    "У default runtime нет поля configuration",
                    code=CODE_RUNTIME_CONFIG_MISMATCH,
                    source="project",
                )
            ]
        selected_conf = _find_by_id(configurations, rt_conf_id)
        if selected_conf is None:
            return None, [
                error(
                    f"default runtime ссылается на неизвестную configuration {rt_conf_id!r}",
                    code=CODE_RUNTIME_CONFIG_MISMATCH,
                    source="project",
                )
            ]
        return _target_from(selected_conf, selected_rt)

    # configuration known
    conf_id = _id_of(selected_conf)
    if conf_id is None:
        return None, [
            error(
                "У выбранной configuration отсутствует id",
                code=CODE_CONFIG_UNKNOWN,
                source="project",
            )
        ]

    if not require_runtime and selected_rt is None:
        return _target_from(selected_conf, None)

    if selected_rt is None:
        related = _runtimes_for_config(runtimes, conf_id)
        selected_rt, diags = _pick_runtime_for_config(related, conf_id=conf_id)
        if selected_rt is None:
            return None, diags

    return _target_from(selected_conf, selected_rt)
