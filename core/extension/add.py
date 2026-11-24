"""Add an extension to an existing configuration project (ADR-023 / #88 / #95 / #163)."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from adapters.edtcli import EdtCliInfo
from adapters.edtcli import RunFn as EdtRunFn
from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_ibcmd import IbcmdError, RunFn, import_cfe_with_ibcmd
from adapters.platform_ibcmd.constants import CODE_IBCMD_FAILED, IBCMD_DATA_REL
from core.diagnostics import error
from core.project.detect import detect_manifest
from core.project.init import (
    _scaffold_extension_sources,
    platform_version_for_manifest,
    sanitize_ext_id,
    sanitize_project_name,
)
from core.project.load import load_manifest
from core.project.paths import project_home, scope_root_from_manifest
from core.project.resolve import resolve_config_runtime
from core.project.result import ProjectResult
from core.project.validate import validate_project
from core.source import run_convert
from core.source.constants import SOURCE_FORMAT_EDT, SOURCE_FORMAT_XML

CODE_EXT_EXISTS = "1CE001"
CODE_EXT_NOT_CONFIG = "1CE002"
CODE_CFE_MISSING = "1CE003"
CODE_IBCMD_MISSING = "1CE004"
CODE_EXT_FORMAT = "1CE005"
CODE_EXT_PATH = "1CE006"
CODE_EXT_PATH_MUTEX = "1CE007"
SUPPORTED_PURPOSES = frozenset({"product", "tests", "other"})
SUPPORTED_SOURCE_FORMATS = frozenset({SOURCE_FORMAT_XML, SOURCE_FORMAT_EDT})

# Scratch IB for .cfe → XML dump (not the project's default runtime).
CFE_IMPORT_RUNTIME_REL = ".1c-dev/runtime/_cfe-import"

ImportCfeFn = Callable[..., list[str]]


def add_extension(
    start: Path | None = None,
    *,
    ext_id: str | None = None,
    name: str | None = None,
    purpose: str = "product",
    config_id: str | None = None,
    force: bool = False,
    from_cfe: Path | str | None = None,
    source_path: Path | str | None = None,
    format: str = SOURCE_FORMAT_XML,
    suite: str | None = "unit",
    run: RunFn | None = None,
    import_cfe_fn: ImportCfeFn | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
    edt_run: EdtRunFn | None = None,
    edt_discover: Callable[[], EdtCliInfo] | None = None,
) -> ProjectResult:
    """
    Append to ``configurations[].extensions[]``.

    Default: scaffold ``src/cfe/<id>/`` (XML).
    With ``from_cfe``: load .cfe into a scratch IB → export hierarchical XML into
    ``src/cfe/<id>/`` (``source.format=xml``). Does not copy the binary .cfe into src.
    With ``source_path``: register an existing layout (in-tree or external for
    ``purpose: tests``) without scaffold (ADR-034). Mutually exclusive with
    ``from_cfe``.

    With ``format=edt`` (#163): after XML scaffold / .cfe export, run
    ``source.convert --to=edt --extension <id>`` so the manifest gets
    ``extensions[].source.format: edt`` and ``path`` stays the EDT project root
    (typically ``src/cfe/<id>/``). For ``source_path``, ``format`` must match layout.
    """
    start_path = (start or Path.cwd()).resolve()
    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return ProjectResult(
            status="error",
            root=start_path,
            diagnostics=[
                error(
                    "Манифест проекта не найден",
                    code="1CP001",
                    suggestion="Выполните 1c-dev init, затем 1c-dev configuration add",
                )
            ],
        )

    root = scope_root_from_manifest(manifest_path)
    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=list(load_diags)
            or [
                error(
                    "Не удалось прочитать манифест",
                    code="1CP002",
                    file=str(manifest_path.name),
                )
            ],
        )

    if str(data.get("schema")) != "2":
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=[
                error(
                    "extension add требует манифест schema \"2\"",
                    code=CODE_EXT_NOT_CONFIG,
                    suggestion="Используйте .1c-dev/project.yaml (schema 2)",
                )
            ],
        )

    configurations = data.get("configurations")
    if isinstance(configurations, list) and not configurations:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=[
                error(
                    "В манифесте нет configurations[] — сначала добавьте configuration",
                    code=CODE_EXT_NOT_CONFIG,
                    suggestion="Выполните 1c-dev configuration add",
                )
            ],
        )

    if purpose not in SUPPORTED_PURPOSES:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=[
                error(
                    f"Неизвестный purpose: {purpose}",
                    code="1CP005",
                    suggestion="Используйте product, tests или other",
                )
            ],
        )

    resolved_format = str(format or SOURCE_FORMAT_XML).strip().lower()
    if resolved_format not in SUPPORTED_SOURCE_FORMATS:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=[
                error(
                    f"Неизвестный format: {format}",
                    code=CODE_EXT_FORMAT,
                    suggestion="Используйте xml или edt",
                )
            ],
        )

    cfe_src: Path | None = None
    if from_cfe is not None and str(from_cfe).strip() != "":
        cfe_src = Path(from_cfe).expanduser().resolve()
        if not cfe_src.is_file():
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        f"Файл .cfe не найден: {cfe_src}",
                        code=CODE_CFE_MISSING,
                        suggestion="Укажите существующий путь через --from",
                    )
                ],
            )
        if cfe_src.suffix.lower() != ".cfe":
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        f"Ожидается файл .cfe, получено: {cfe_src.name}",
                        code=CODE_CFE_MISSING,
                        suggestion="Передайте путь к файлу расширения (.cfe)",
                    )
                ],
            )

    existing_src: Path | None = None
    if source_path is not None and str(source_path).strip() != "":
        if cfe_src is not None:
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        "--path и --from взаимоисключающие",
                        code=CODE_EXT_PATH_MUTEX,
                        suggestion=(
                            "Укажите либо --path (существующие исходники), "
                            "либо --from (.cfe)"
                        ),
                    )
                ],
            )
        existing_src = Path(source_path).expanduser()
        if not existing_src.is_absolute():
            existing_src = (root / existing_src).resolve()
        else:
            existing_src = existing_src.resolve()
        if not existing_src.is_dir():
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        f"Каталог исходников не найден: {existing_src}",
                        code=CODE_EXT_PATH,
                        suggestion="Укажите существующий каталог XML/EDT через --path",
                    )
                ],
            )

    target, resolve_diags = resolve_config_runtime(
        data,
        config_id=config_id,
        require_runtime=False,
    )
    if target is None:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=list(resolve_diags),
        )

    conf = target.configuration
    if conf.get("type") != "configuration":
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=[
                error(
                    "extension add применим только к configurations[].type=configuration",
                    code=CODE_EXT_NOT_CONFIG,
                    suggestion="Выберите --config с type configuration",
                )
            ],
        )

    if existing_src is not None:
        default_stem = existing_src.name
    elif cfe_src is not None:
        default_stem = cfe_src.stem
    else:
        default_stem = "custom"
    resolved_id = sanitize_ext_id(ext_id or name or default_stem)
    resolved_name = sanitize_project_name(name or ext_id or resolved_id)

    existing = conf.get("extensions")
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, dict):
                continue
            if item.get("id") == resolved_id or item.get("name") == resolved_name:
                return ProjectResult(
                    status="error",
                    path=manifest_path,
                    root=root,
                    home=project_home(root),
                    diagnostics=[
                        error(
                            f"Расширение уже есть в манифесте: id={resolved_id!r} "
                            f"или name={resolved_name!r}",
                            code=CODE_EXT_EXISTS,
                            suggestion="Укажите другой --id/--name или --force",
                        )
                    ],
                )

    created: list[str] = []
    from adapters.source.edt.detect import is_edt_project_root
    from adapters.source.xml.detect import is_xml_source_root
    from core.project.source_paths import (
        is_within_scope,
        store_source_path,
    )
    from core.test.suites import ensure_unit_suite

    if existing_src is not None:
        # Register existing layout (ADR-034); no scaffold / convert.
        layout_format = resolved_format
        if layout_format == SOURCE_FORMAT_XML and not is_xml_source_root(existing_src):
            if is_edt_project_root(existing_src):
                layout_format = SOURCE_FORMAT_EDT
            else:
                return ProjectResult(
                    status="error",
                    path=manifest_path,
                    root=root,
                    home=project_home(root),
                    diagnostics=[
                        error(
                            f"Каталог не является корнем XML/EDT: {existing_src}",
                            code=CODE_EXT_PATH,
                            suggestion=(
                                "Укажите каталог с Configuration.xml "
                                "или EDT-проект (.project / Configuration.mdo)"
                            ),
                        )
                    ],
                )
        elif layout_format == SOURCE_FORMAT_EDT and not is_edt_project_root(
            existing_src
        ):
            if is_xml_source_root(existing_src):
                layout_format = SOURCE_FORMAT_XML
            else:
                return ProjectResult(
                    status="error",
                    path=manifest_path,
                    root=root,
                    home=project_home(root),
                    diagnostics=[
                        error(
                            f"Каталог не является корнем EDT: {existing_src}",
                            code=CODE_EXT_PATH,
                            suggestion="Укажите корень EDT-проекта или --format xml",
                        )
                    ],
                )

        if purpose != "tests" and not is_within_scope(root, existing_src):
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        "Путь вне scope допустим только для --purpose tests",
                        code=CODE_EXT_PATH,
                        suggestion=(
                            "Скопируйте расширение в scope или укажите --purpose tests"
                        ),
                    )
                ],
            )

        source_rel = store_source_path(root, existing_src)
        source_entry = {"format": layout_format, "path": source_rel}

        configurations = data.get("configurations")
        if not isinstance(configurations, list):
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                diagnostics=[error("configurations[] отсутствует", code="1CP002")],
            )

        patched = False
        for item in configurations:
            if not isinstance(item, dict):
                continue
            if item.get("id") != target.config_id:
                continue
            exts: list[Any] = list(item.get("extensions") or [])
            if not isinstance(item.get("extensions"), list):
                exts = []
            exts.append(
                {
                    "id": resolved_id,
                    "name": resolved_name,
                    "purpose": purpose,
                    "source": source_entry,
                }
            )
            item["extensions"] = exts
            if purpose == "tests" and suite:
                ensure_unit_suite(item, [resolved_id])
                if suite != "unit":
                    # Optional non-default suite id: ensure named suite too.
                    tests = item.get("tests")
                    if not isinstance(tests, list):
                        tests = []
                        item["tests"] = tests
                    if not any(
                        isinstance(s, dict) and s.get("id") == suite for s in tests
                    ):
                        tests.append(
                            {
                                "id": suite,
                                "runner": "yaxunit",
                                "extensions": [resolved_id],
                            }
                        )
            patched = True
            break

        if not patched:
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                diagnostics=[
                    error(
                        f"Configuration {target.config_id!r} не найдена при записи",
                        code="1CP002",
                    )
                ],
            )

        try:
            manifest_path.write_text(
                yaml.safe_dump(
                    data,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False,
                ),
                encoding="utf-8",
                newline="\n",
            )
        except OSError as exc:
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                diagnostics=[
                    error(f"Не удалось записать манифест: {exc}", code="1CP006")
                ],
            )

        result = validate_project(root)
        result.created = created
        result.updated = [str(manifest_path.relative_to(root))]
        return result

    source_rel = f"src/cfe/{resolved_id}"
    source_dir = (root / source_rel).resolve()

    if cfe_src is not None:
        if source_dir.exists() and any(source_dir.iterdir()) and not force:
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        f"Каталог исходников уже существует: {source_rel}",
                        code="1CP004",
                        suggestion="Укажите --force для перезаписи XML из .cfe",
                    )
                ],
            )

        discovery = (discover or discover_environment)()
        ibcmd_info = discovery.ibcmd
        if not ibcmd_info.found or ibcmd_info.path is None:
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        "ibcmd не найден — нужен для выгрузки .cfe в XML",
                        code=CODE_IBCMD_MISSING,
                        source="platform",
                        suggestion=(
                            "Установите платформу 1С с ibcmd "
                            "или укажите path к ibcmd в PATH"
                        ),
                    )
                ],
            )

        if source_dir.exists() and force:
            shutil.rmtree(source_dir)
        source_dir.mkdir(parents=True, exist_ok=True)

        db_path = (root / CFE_IMPORT_RUNTIME_REL).resolve()
        data_path = (root / IBCMD_DATA_REL).resolve()
        importer = import_cfe_fn or import_cfe_with_ibcmd
        try:
            importer(
                ibcmd_info.path,
                db_path=db_path,
                data_path=data_path,
                cfe_path=cfe_src,
                source_dir=source_dir,
                extension=resolved_name,
                run=run,
            )
        except IbcmdError as exc:
            if source_dir.exists():
                shutil.rmtree(source_dir, ignore_errors=True)
            diags = list(exc.diagnostics) or [
                error(exc.message, code=exc.code, source="platform")
            ]
            for diag in diags:
                if diag.get("severity") == "error" and not diag.get("suggestion"):
                    diag["suggestion"] = (
                        "Имя --name должно совпадать с именем расширения внутри .cfe; "
                        "нужен ibcmd с support load/export --extension"
                    )
                    break
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=diags,
            )
        except OSError as exc:
            if source_dir.exists():
                shutil.rmtree(source_dir, ignore_errors=True)
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(f"Ошибка выгрузки .cfe в XML: {exc}", code="1CP006")
                ],
            )

        if not (source_dir / "Configuration.xml").is_file():
            shutil.rmtree(source_dir, ignore_errors=True)
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        "После export нет Configuration.xml — выгрузка .cfe не удалась",
                        code=CODE_IBCMD_FAILED,
                        source="platform",
                        suggestion=(
                            "Проверьте, что --name совпадает с именем в .cfe "
                            "и ibcmd поддерживает config load/export --extension"
                        ),
                    )
                ],
            )
        created.append(source_rel)
    else:
        discovery = (discover or discover_environment)()
        platform_version = platform_version_for_manifest(discovery.platform.version)

        try:
            created = _scaffold_extension_sources(
                root,
                ext_id=resolved_id,
                name=resolved_name,
                platform_version=platform_version,
                force=force,
            )
        except FileExistsError as exc:
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        str(exc),
                        code="1CP004",
                        suggestion="Укажите --force для перезаписи исходников",
                    )
                ],
            )
        except (OSError, FileNotFoundError, KeyError) as exc:
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        f"Ошибка scaffold расширения: {exc}",
                        code="1CP006",
                    )
                ],
            )

    source_entry = {"format": "xml", "path": source_rel}

    # Patch configurations[].extensions[]
    configurations = data.get("configurations")
    if not isinstance(configurations, list):
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            diagnostics=[error("configurations[] отсутствует", code="1CP002")],
        )

    from core.test.suites import ensure_unit_suite

    patched = False
    for item in configurations:
        if not isinstance(item, dict):
            continue
        if item.get("id") != target.config_id:
            continue
        scaffold_exts: list[Any] = list(item.get("extensions") or [])
        if not isinstance(item.get("extensions"), list):
            scaffold_exts = []
        scaffold_exts.append(
            {
                "id": resolved_id,
                "name": resolved_name,
                "purpose": purpose,
                "source": source_entry,
            }
        )
        item["extensions"] = scaffold_exts
        if purpose == "tests" and suite:
            ensure_unit_suite(item, [resolved_id])
        patched = True
        break

    if not patched:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            diagnostics=[
                error(
                    f"Configuration {target.config_id!r} не найдена при записи",
                    code="1CP002",
                )
            ],
        )

    try:
        manifest_path.write_text(
            yaml.safe_dump(
                data,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ),
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            diagnostics=[
                error(f"Не удалось записать манифест: {exc}", code="1CP006")
            ],
        )

    if resolved_format == SOURCE_FORMAT_EDT:
        convert = run_convert(
            root,
            to="edt",
            config_id=target.config_id,
            extension_id=resolved_id,
            force=force,
            edt_run=edt_run,
            edt_discover=edt_discover,
        )
        if convert.status != "ok":
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                created=created,
                updated=[str(manifest_path.relative_to(root))],
                diagnostics=list(convert.diagnostics)
                or [
                    error(
                        "Не удалось конвертировать расширение в EDT",
                        code=CODE_EXT_FORMAT,
                        suggestion="Проверьте 1cedtcli (doctor) или повторите source convert",
                    )
                ],
            )

    result = validate_project(root)
    result.created = created
    result.updated = [str(manifest_path.relative_to(root))]
    return result
