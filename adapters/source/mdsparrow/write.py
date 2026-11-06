"""EDT semantic write via md-sparrow apply-mutation (ADR-032 path D / #154)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from adapters.source.edt.constants import CONFIGURATION_MDO_REL
from adapters.source.mdsparrow.constants import (
    ENV_UNAVAILABLE_CODE,
    GAP_CODE,
    MUTATION_FAILED_CODE,
)
from adapters.source.mdsparrow.dto import (
    attr_type_dto,
    number_precision_gap,
    parse_attr_shorthand,
    parse_named_synonym,
    parse_property_assignment,
)
from adapters.source.mdsparrow.mutation import (
    ApplyMutationResult,
    MdSparrowError,
    apply_mutation,
)
from adapters.source.mdsparrow.paths import (
    DEFAULT_SCHEMA_VERSION,
    configuration_mdo_path,
    object_mdo_path,
    object_mdo_rel,
)
from adapters.source.mdsparrow.resolve import ToolResolve, resolve_jar, resolve_java
from adapters.source.xmlgen.edit import EditOp, EditResult

if TYPE_CHECKING:
    from core.metadata.ir import CatalogObject


@dataclass
class EdtWriteResult:
    """Paths touched + soft gap warnings from an EDT write."""

    changed_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Parallel to ``warnings``; ``1CS010`` for Number/TS soft gaps (ADR-032).
    warning_codes: list[str | None] = field(default_factory=list)
    stdout: str = ""


def _append_warning(
    warnings: list[str],
    codes: list[str | None],
    message: str,
    *,
    code: str | None = None,
) -> None:
    """Append a soft warning and its structured diagnostic code (or None)."""
    warnings.append(message)
    codes.append(code)


def _require_tools(
    *,
    jar: ToolResolve | None,
    java: ToolResolve | None,
) -> tuple[ToolResolve, ToolResolve]:
    jar_r = jar if jar is not None else resolve_jar()
    java_r = java if java is not None else resolve_java()
    if not java_r.found or java_r.path is None:
        raise MdSparrowError(
            "Java 25+ не найдена (нужна для md-sparrow)",
            code=ENV_UNAVAILABLE_CODE,
        )
    if not jar_r.found or jar_r.path is None:
        raise MdSparrowError(
            "md-sparrow jar не найден",
            code=ENV_UNAVAILABLE_CODE,
        )
    return jar_r, java_r


def _mut(
    params: dict[str, Any],
    *,
    jar: ToolResolve,
    java: ToolResolve,
    cwd: Path | None = None,
) -> ApplyMutationResult:
    return apply_mutation(params, jar=jar, java=java, cwd=cwd)


def read_object_dto(
    object_mdo: Path,
    *,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
    schema_version: str = DEFAULT_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Run ``cf-md-object-get`` (works on ``.mdo`` via EDT router)."""
    jar_r, java_r = _require_tools(jar=jar, java=java)
    object_mdo = object_mdo.resolve()
    if not object_mdo.is_file():
        raise MdSparrowError(
            f"Файл объекта не найден: {object_mdo}",
            code="1CM008",
        )
    cmd = [
        str(java_r.path),
        "-jar",
        str(jar_r.path),
        "cf-md-object-get",
        "-v",
        schema_version,
        str(object_mdo),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        msg = "md-sparrow cf-md-object-get завершился с ошибкой"
        if detail:
            msg = f"{msg}: {detail[:500]}"
        raise MdSparrowError(msg, code=MUTATION_FAILED_CODE)
    try:
        payload = json.loads(proc.stdout or "")
    except json.JSONDecodeError as exc:
        raise MdSparrowError(
            "md-sparrow cf-md-object-get вернул не-JSON",
            code=MUTATION_FAILED_CODE,
        ) from exc
    if not isinstance(payload, dict):
        raise MdSparrowError(
            "md-sparrow cf-md-object-get: ожидался JSON-объект",
            code=MUTATION_FAILED_CODE,
        )
    return payload


def _set_object_dto(
    object_mdo: Path,
    dto: dict[str, Any],
    *,
    jar: ToolResolve,
    java: ToolResolve,
    schema_version: str = DEFAULT_SCHEMA_VERSION,
) -> None:
    _mut(
        {
            "op": "cf-md-object-set",
            "objectXml": str(object_mdo.resolve()),
            "schemaVersion": schema_version,
            "payloadJson": json.dumps(dto, ensure_ascii=False),
        },
        jar=jar,
        java=java,
    )


def _find_attr(dto: dict[str, Any], name: str) -> dict[str, Any] | None:
    attrs = dto.get("attributes")
    if not isinstance(attrs, list):
        return None
    for item in attrs:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def _find_ts(dto: dict[str, Any], name: str) -> dict[str, Any] | None:
    sections = dto.get("tabularSections")
    if not isinstance(sections, list):
        return None
    for item in sections:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def _find_enum_value(dto: dict[str, Any], name: str) -> dict[str, Any] | None:
    values = dto.get("enumValues")
    if not isinstance(values, list):
        return None
    for item in values:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def _find_named(
    dto: dict[str, Any],
    key: str,
    name: str,
) -> dict[str, Any] | None:
    items = dto.get(key)
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def _apply_attr_fields(
    target: dict[str, Any],
    attr: Any,
) -> list[tuple[str, str | None]]:
    """Patch attribute DTO in-place; return (message, code) soft warnings."""
    out: list[tuple[str, str | None]] = []
    if attr.synonym:
        target["synonym"] = attr.synonym
    try:
        target["type"] = attr_type_dto(attr)
    except ValueError as exc:
        out.append((str(exc), None))
        return out
    if number_precision_gap(attr):
        out.append(
            (
                f"Number precision/scale для {attr.name!r} может не сохраниться "
                f"в .mdo (известный gap md-sparrow / bake-off S2)",
                GAP_CODE,
            )
        )
    return out


def _extend_warnings(
    warnings: list[str],
    codes: list[str | None],
    items: list[tuple[str, str | None]],
) -> None:
    for message, code in items:
        _append_warning(warnings, codes, message, code=code)


def create_edt_object(
    edt_root: Path,
    catalog: CatalogObject,
    *,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
    schema_version: str = DEFAULT_SCHEMA_VERSION,
) -> EdtWriteResult:
    """
    Create metadata object + children via apply-mutation (path D).

    Object synonym and attribute types/synonyms are applied via
    ``cf-md-object-set`` (``synonymRu`` on add-md-object is a known no-op gap).
    """
    jar_r, java_r = _require_tools(jar=jar, java=java)
    edt_root = edt_root.resolve()
    cfg = configuration_mdo_path(edt_root)
    if not cfg.is_file():
        raise MdSparrowError(
            f"Configuration.mdo не найден: {cfg}",
            code="1CS003",
        )
    obj_path = object_mdo_path(edt_root, catalog.type, catalog.name)
    if obj_path.is_file():
        raise MdSparrowError(
            f"Объект уже существует: {catalog.qualified_name}",
            code="1CM003",
        )

    warnings: list[str] = []
    warning_codes: list[str | None] = []
    add_params: dict[str, Any] = {
        "op": "add-md-object",
        "configurationXml": str(cfg),
        "type": catalog.type,
        "name": catalog.name,
        "schemaVersion": schema_version,
    }
    if catalog.type == "Catalog" and catalog.synonym:
        # Best-effort; may be ignored — object-set below is the workaround.
        add_params["synonymRu"] = catalog.synonym
    _mut(add_params, jar=jar_r, java=java_r)

    child_ops: list[dict[str, Any]] = []
    for attr in catalog.attributes:
        child_ops.append(
            {
                "op": "cf-md-attribute-add",
                "objectXml": str(obj_path),
                "name": attr.name,
                "schemaVersion": schema_version,
            }
        )
    for section in catalog.tabular_sections:
        child_ops.append(
            {
                "op": "cf-md-tabular-section-add",
                "objectXml": str(obj_path),
                "name": section.name,
                "schemaVersion": schema_version,
            }
        )
        for attr in section.attributes:
            child_ops.append(
                {
                    "op": "cf-md-tabular-attribute-add",
                    "objectXml": str(obj_path),
                    "tabularSection": section.name,
                    "name": attr.name,
                    "schemaVersion": schema_version,
                }
            )
    for value in catalog.values:
        child_ops.append(
            {
                "op": "cf-md-enum-value-add",
                "objectXml": str(obj_path),
                "name": value.name,
                "schemaVersion": schema_version,
            }
        )
    for dim in catalog.dimensions:
        child_ops.append(
            {
                "op": "cf-md-dimension-add",
                "objectXml": str(obj_path),
                "name": dim.name,
                "schemaVersion": schema_version,
            }
        )
    for res in catalog.resources:
        child_ops.append(
            {
                "op": "cf-md-resource-add",
                "objectXml": str(obj_path),
                "name": res.name,
                "schemaVersion": schema_version,
            }
        )

    if child_ops:
        if len(child_ops) == 1:
            _mut(child_ops[0], jar=jar_r, java=java_r)
        else:
            _mut(
                {"op": "batch", "operations": child_ops},
                jar=jar_r,
                java=java_r,
            )

    need_set = bool(catalog.synonym) or any(
        a.synonym or a.type != "String" or a.length not in (None, 10)
        for a in catalog.attributes
    )
    if not need_set:
        for section in catalog.tabular_sections:
            if section.synonym or section.attributes:
                need_set = True
                break
    if not need_set:
        for value in catalog.values:
            if value.synonym:
                need_set = True
                break
    if not need_set:
        for dim in catalog.dimensions:
            if dim.synonym or dim.type != "String" or dim.length not in (None, 10):
                need_set = True
                break
    if not need_set:
        for res in catalog.resources:
            if res.synonym or res.type != "String" or res.length not in (None, 10):
                need_set = True
                break

    # CommonModule flags → object-set properties.
    flag_props = _common_module_flag_props(catalog)
    if flag_props:
        need_set = True

    if need_set:
        dto = read_object_dto(
            obj_path, jar=jar_r, java=java_r, schema_version=schema_version
        )
        if catalog.synonym:
            dto["synonym"] = catalog.synonym
        for attr in catalog.attributes:
            target = _find_attr(dto, attr.name)
            if target is None:
                _append_warning(
                    warnings,
                    warning_codes,
                    f"Реквизит {attr.name!r} не найден после add",
                )
                continue
            _extend_warnings(warnings, warning_codes, _apply_attr_fields(target, attr))
        for section in catalog.tabular_sections:
            ts = _find_ts(dto, section.name)
            if ts is None:
                _append_warning(
                    warnings,
                    warning_codes,
                    f"ТЧ {section.name!r} не найдена после add",
                )
                continue
            if section.synonym:
                ts["synonym"] = section.synonym
                _append_warning(
                    warnings,
                    warning_codes,
                    f"Синоним ТЧ {section.name!r} может не сохраниться в .mdo "
                    f"(известный gap)",
                    code=GAP_CODE,
                )
            ts_attrs = ts.get("attributes")
            if not isinstance(ts_attrs, list):
                ts_attrs = []
                ts["attributes"] = ts_attrs
            for attr in section.attributes:
                target = next(
                    (
                        a
                        for a in ts_attrs
                        if isinstance(a, dict) and a.get("name") == attr.name
                    ),
                    None,
                )
                if target is None:
                    _append_warning(
                        warnings,
                        warning_codes,
                        f"Реквизит ТЧ {section.name}.{attr.name} не найден после add",
                    )
                    continue
                _extend_warnings(
                    warnings, warning_codes, _apply_attr_fields(target, attr)
                )
                _append_warning(
                    warnings,
                    warning_codes,
                    f"Тип/синоним реквизита ТЧ {section.name}.{attr.name} "
                    f"может не сохраниться в .mdo (известный gap)",
                    code=GAP_CODE,
                )
        for value in catalog.values:
            if not value.synonym:
                continue
            ev = _find_enum_value(dto, value.name)
            if ev is None:
                _append_warning(
                    warnings,
                    warning_codes,
                    f"Значение перечисления {value.name!r} не найдено",
                )
                continue
            ev["synonym"] = value.synonym
        for dim in catalog.dimensions:
            target = _find_named(dto, "dimensions", dim.name)
            if target is None:
                _append_warning(
                    warnings,
                    warning_codes,
                    f"Измерение {dim.name!r} не найдено после add",
                )
                continue
            _extend_warnings(warnings, warning_codes, _apply_attr_fields(target, dim))
        for res in catalog.resources:
            target = _find_named(dto, "resources", res.name)
            if target is None:
                _append_warning(
                    warnings,
                    warning_codes,
                    f"Ресурс {res.name!r} не найден после add",
                )
                continue
            _extend_warnings(warnings, warning_codes, _apply_attr_fields(target, res))
        for prop, val in flag_props.items():
            _set_dto_property(dto, prop, val)
        _set_object_dto(
            obj_path,
            dto,
            jar=jar_r,
            java=java_r,
            schema_version=schema_version,
        )

    changed = [object_mdo_rel(catalog.type, catalog.name), CONFIGURATION_MDO_REL]
    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for rel in changed:
        if rel not in seen:
            seen.add(rel)
            ordered.append(rel)
    return EdtWriteResult(
        changed_paths=ordered,
        warnings=warnings,
        warning_codes=warning_codes,
    )


def _common_module_flag_props(catalog: CatalogObject) -> dict[str, Any]:
    if catalog.type != "CommonModule":
        return {}
    props: dict[str, Any] = {}
    mapping = (
        ("server", "server"),
        ("client_managed_application", "clientManagedApplication"),
        ("client_ordinary_application", "clientOrdinaryApplication"),
        ("server_call", "serverCall"),
        ("external_connection", "externalConnection"),
        ("privileged", "privileged"),
        ("global_", "global"),
    )
    for attr_name, dto_key in mapping:
        val = getattr(catalog, attr_name, None)
        if val is not None:
            props[dto_key] = bool(val)
    reuse = getattr(catalog, "return_values_reuse", None)
    if reuse is not None:
        props["returnValuesReuse"] = reuse
    return props


def _set_dto_property(dto: dict[str, Any], prop: str, value: Any) -> None:
    """Map Designer/IR property names onto cf-md-object-get DTO keys."""
    lower = prop.lower().replace("_", "")
    # Synonym on object root.
    if lower == "synonym":
        dto["synonym"] = value
        return
    # CommonModule lives under nested block in some schemas; try flat first.
    camel_map = {
        "server": "server",
        "clientmanagedapplication": "clientManagedApplication",
        "clientordinaryapplication": "clientOrdinaryApplication",
        "servercall": "serverCall",
        "externalconnection": "externalConnection",
        "privileged": "privileged",
        "global": "global",
        "returnvaluesreuse": "returnValuesReuse",
    }
    key = camel_map.get(lower, prop[:1].lower() + prop[1:] if prop else prop)
    module = dto.get("commonModule")
    if isinstance(module, dict) and (
        key in module or lower in {k.lower() for k in module}
    ):
        module[key] = _coerce_flag(value)
        return
    dto[key] = _coerce_flag(value)


def _coerce_flag(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lower = value.lower()
        if lower in {"true", "1", "yes"}:
            return True
        if lower in {"false", "0", "no"}:
            return False
    return value


def delete_edt_object(
    edt_root: Path,
    obj_type: str,
    name: str,
    *,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
) -> EdtWriteResult:
    """Delete metadata object via ``cf-md-object-delete`` apply-mutation."""
    jar_r, java_r = _require_tools(jar=jar, java=java)
    edt_root = edt_root.resolve()
    cfg = configuration_mdo_path(edt_root)
    obj_path = object_mdo_path(edt_root, obj_type, name)
    if not obj_path.is_file():
        raise MdSparrowError(
            f"Объект не найден: {obj_type}.{name}",
            code="1CM008",
        )
    _mut(
        {
            "op": "cf-md-object-delete",
            "configurationXml": str(cfg),
            "objectXml": str(obj_path),
            "tag": obj_type,
            "name": name,
        },
        jar=jar_r,
        java=java_r,
    )
    return EdtWriteResult(
        changed_paths=[
            object_mdo_rel(obj_type, name),
            CONFIGURATION_MDO_REL,
        ]
    )


def update_edt_object(
    edt_root: Path,
    obj_type: str,
    name: str,
    operations: list[EditOp],
    *,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
    schema_version: str = DEFAULT_SCHEMA_VERSION,
) -> EditResult:
    """
    Apply xml-gen-shaped EditOps on an EDT ``.mdo`` via apply-mutation.

    Unsupported / gap ops raise MdSparrowError with ``1CS010`` or emit warnings.
    """
    jar_r, java_r = _require_tools(jar=jar, java=java)
    edt_root = edt_root.resolve()
    obj_path = object_mdo_path(edt_root, obj_type, name)
    if not obj_path.is_file():
        raise MdSparrowError(
            f"Объект не найден: {obj_type}.{name}",
            code="1CM008",
        )

    result = EditResult()
    dto_dirty = False
    dto: dict[str, Any] | None = None

    def ensure_dto() -> dict[str, Any]:
        nonlocal dto
        if dto is None:
            dto = read_object_dto(
                obj_path, jar=jar_r, java=java_r, schema_version=schema_version
            )
        return dto

    for op in operations:
        if op.op == "add-attribute":
            attr = parse_attr_shorthand(op.value)
            _mut(
                {
                    "op": "cf-md-attribute-add",
                    "objectXml": str(obj_path),
                    "name": attr.name,
                    "schemaVersion": schema_version,
                },
                jar=jar_r,
                java=java_r,
            )
            dto = None
            dto_dirty = False
            d = ensure_dto()
            target = _find_attr(d, attr.name)
            if target is not None:
                _extend_warnings(
                    result.warnings,
                    result.warning_codes,
                    _apply_attr_fields(target, attr),
                )
                dto_dirty = True
            result.added += 1
        elif op.op == "remove-attribute":
            attr_name = op.value.strip()
            _mut(
                {
                    "op": "cf-md-attribute-delete",
                    "objectXml": str(obj_path),
                    "name": attr_name,
                    "schemaVersion": schema_version,
                },
                jar=jar_r,
                java=java_r,
            )
            dto = None
            dto_dirty = False
            result.removed += 1
        elif op.op == "modify-attribute":
            attr_name, synonym = parse_named_synonym(op.value)
            d = ensure_dto()
            target = _find_attr(d, attr_name)
            if target is None:
                _append_warning(
                    result.warnings,
                    result.warning_codes,
                    f"Реквизит {attr_name!r} не найден для modify",
                )
            else:
                if synonym is not None:
                    target["synonym"] = synonym
                    dto_dirty = True
                    result.modified += 1
        elif op.op == "add-ts":
            raw_ts = op.value.strip()
            if ":" in raw_ts:
                ts_name, synonym_raw = raw_ts.split(":", 1)
                ts_name = ts_name.strip()
                synonym_raw = synonym_raw.strip()
                if synonym_raw.lower().startswith("synonym="):
                    synonym = synonym_raw.split("=", 1)[1].strip() or None
                else:
                    synonym = synonym_raw or None
            else:
                ts_name = raw_ts
                synonym = None
            _mut(
                {
                    "op": "cf-md-tabular-section-add",
                    "objectXml": str(obj_path),
                    "name": ts_name,
                    "schemaVersion": schema_version,
                },
                jar=jar_r,
                java=java_r,
            )
            dto = None
            dto_dirty = False
            if synonym:
                d = ensure_dto()
                ts = _find_ts(d, ts_name)
                if ts is not None:
                    ts["synonym"] = synonym
                    dto_dirty = True
                    _append_warning(
                        result.warnings,
                        result.warning_codes,
                        f"Синоним ТЧ {ts_name!r} может не сохраниться (известный gap)",
                        code=GAP_CODE,
                    )
            result.added += 1
        elif op.op == "remove-ts":
            ts_name = op.value.strip()
            _mut(
                {
                    "op": "cf-md-tabular-section-delete",
                    "objectXml": str(obj_path),
                    "name": ts_name,
                    "schemaVersion": schema_version,
                },
                jar=jar_r,
                java=java_r,
            )
            dto = None
            dto_dirty = False
            result.removed += 1
        elif op.op == "modify-ts":
            ts_name, synonym = parse_named_synonym(op.value)
            d = ensure_dto()
            ts = _find_ts(d, ts_name)
            if ts is None:
                _append_warning(
                    result.warnings,
                    result.warning_codes,
                    f"ТЧ {ts_name!r} не найдена для modify",
                )
            elif synonym is not None:
                ts["synonym"] = synonym
                dto_dirty = True
                result.modified += 1
                _append_warning(
                    result.warnings,
                    result.warning_codes,
                    f"Синоним ТЧ {ts_name!r} может не сохраниться (известный gap)",
                    code=GAP_CODE,
                )
        elif op.op == "add-ts-attribute":
            # value: TS.Name:TypeSpec
            raw = op.value.strip()
            if "." not in raw:
                raise MdSparrowError(
                    f"add-ts-attribute ожидает TS.Name:Type…, получено: {op.value!r}",
                    code="1CM002",
                )
            ts_name, rest = raw.split(".", 1)
            attr = parse_attr_shorthand(rest)
            _mut(
                {
                    "op": "cf-md-tabular-attribute-add",
                    "objectXml": str(obj_path),
                    "tabularSection": ts_name.strip(),
                    "name": attr.name,
                    "schemaVersion": schema_version,
                },
                jar=jar_r,
                java=java_r,
            )
            dto = None
            dto_dirty = False
            result.added += 1
            _append_warning(
                result.warnings,
                result.warning_codes,
                f"Тип/синоним реквизита ТЧ {ts_name.strip()}.{attr.name} "
                f"может не сохраниться (известный gap)",
                code=GAP_CODE,
            )
        elif op.op == "remove-ts-attribute":
            raw = op.value.strip()
            if "." not in raw:
                raise MdSparrowError(
                    f"remove-ts-attribute ожидает TS.Name, получено: {op.value!r}",
                    code="1CM002",
                )
            ts_name, attr_name = raw.split(".", 1)
            _mut(
                {
                    "op": "cf-md-tabular-attribute-delete",
                    "objectXml": str(obj_path),
                    "tabularSection": ts_name.strip(),
                    "name": attr_name.strip(),
                    "schemaVersion": schema_version,
                },
                jar=jar_r,
                java=java_r,
            )
            dto = None
            dto_dirty = False
            result.removed += 1
        elif op.op == "add-enumValue":
            ev_name = op.value.strip()
            _mut(
                {
                    "op": "cf-md-enum-value-add",
                    "objectXml": str(obj_path),
                    "name": ev_name,
                    "schemaVersion": schema_version,
                },
                jar=jar_r,
                java=java_r,
            )
            dto = None
            dto_dirty = False
            result.added += 1
        elif op.op == "remove-enumValue":
            _mut(
                {
                    "op": "cf-md-enum-value-delete",
                    "objectXml": str(obj_path),
                    "name": op.value.strip(),
                    "schemaVersion": schema_version,
                },
                jar=jar_r,
                java=java_r,
            )
            dto = None
            dto_dirty = False
            result.removed += 1
        elif op.op == "modify-enumValue":
            ev_name, synonym = parse_named_synonym(op.value)
            d = ensure_dto()
            ev = _find_enum_value(d, ev_name)
            if ev is None:
                _append_warning(
                    result.warnings,
                    result.warning_codes,
                    f"Значение {ev_name!r} не найдено",
                )
            elif synonym is not None:
                ev["synonym"] = synonym
                dto_dirty = True
                result.modified += 1
        elif op.op in {"add-dimension", "add-resource"}:
            attr = parse_attr_shorthand(op.value)
            sparrow_op = (
                "cf-md-dimension-add"
                if op.op == "add-dimension"
                else "cf-md-resource-add"
            )
            _mut(
                {
                    "op": sparrow_op,
                    "objectXml": str(obj_path),
                    "name": attr.name,
                    "schemaVersion": schema_version,
                },
                jar=jar_r,
                java=java_r,
            )
            dto = None
            dto_dirty = False
            key = "dimensions" if op.op == "add-dimension" else "resources"
            d = ensure_dto()
            target = _find_named(d, key, attr.name)
            if target is not None:
                _extend_warnings(
                    result.warnings,
                    result.warning_codes,
                    _apply_attr_fields(target, attr),
                )
                dto_dirty = True
            result.added += 1
        elif op.op in {"remove-dimension", "remove-resource"}:
            sparrow_op = (
                "cf-md-dimension-delete"
                if op.op == "remove-dimension"
                else "cf-md-resource-delete"
            )
            _mut(
                {
                    "op": sparrow_op,
                    "objectXml": str(obj_path),
                    "name": op.value.strip(),
                    "schemaVersion": schema_version,
                },
                jar=jar_r,
                java=java_r,
            )
            dto = None
            dto_dirty = False
            result.removed += 1
        elif op.op in {"modify-dimension", "modify-resource"}:
            child_name, synonym = parse_named_synonym(op.value)
            key = "dimensions" if op.op == "modify-dimension" else "resources"
            d = ensure_dto()
            target = _find_named(d, key, child_name)
            if target is None:
                _append_warning(
                    result.warnings,
                    result.warning_codes,
                    f"{child_name!r} не найден для {op.op}",
                )
            elif synonym is not None:
                target["synonym"] = synonym
                dto_dirty = True
                result.modified += 1
        elif op.op == "modify-property":
            prop, val = parse_property_assignment(op.value)
            d = ensure_dto()
            _set_dto_property(d, prop, val)
            dto_dirty = True
            result.modified += 1
        elif op.op == "add-exchange-content":
            raise MdSparrowError(
                "add-exchange-content на EDT пока не поддержан "
                f"(gap; code {GAP_CODE})",
                code=GAP_CODE,
            )
        else:
            raise MdSparrowError(
                f"Операция {op.op!r} не поддержана для source.format: edt "
                f"(gap; code {GAP_CODE})",
                code=GAP_CODE,
            )

    if dto_dirty and dto is not None:
        _set_object_dto(
            obj_path,
            dto,
            jar=jar_r,
            java=java_r,
            schema_version=schema_version,
        )

    result.changed_paths = [str(obj_path)]
    return result
