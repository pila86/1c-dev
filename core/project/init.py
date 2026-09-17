"""Bootstrap a new 1C project from templates (ADR-006)."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from adapters.platform import discover_environment
from core.diagnostics import error
from core.project.constants import MANIFEST_NAME
from core.project.result import ProjectResult
from core.project.validate import validate_project

SUPPORTED_TYPES = frozenset({"configuration"})
DEFAULT_PLATFORM_VERSION = "8.3.27"

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")
_NAME_SAFE_RE = re.compile(r"[^0-9A-Za-zА-Яа-яЁё_]+")


def templates_root() -> Path:
    """Resolve templates/ directory (repo root or next to installed package)."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "templates",
        here.parents[3] / "templates",
    ]
    for candidate in candidates:
        if (candidate / "configuration").is_dir():
            return candidate
    raise FileNotFoundError("Каталог templates/ не найден рядом с установкой 1c-dev")


def sanitize_project_name(raw: str) -> str:
    """Normalize a directory/name into a configuration identifier."""
    cleaned = _NAME_SAFE_RE.sub("_", raw.strip())
    cleaned = cleaned.strip("_")
    if not cleaned:
        return "Configuration"
    if cleaned[0].isdigit():
        cleaned = f"C_{cleaned}"
    return cleaned


def default_project_name(target: Path) -> str:
    """Default project name from target directory."""
    return sanitize_project_name(target.resolve().name)


def platform_version_for_manifest(version: str | None) -> str:
    """Reduce full platform version (8.3.27.1549) to major.minor.build."""
    if not version:
        return DEFAULT_PLATFORM_VERSION
    parts = version.split(".")
    if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
        return ".".join(parts[:3])
    if len(parts) >= 2 and all(p.isdigit() for p in parts[:2]):
        return ".".join(parts[:2])
    return DEFAULT_PLATFORM_VERSION


def compatibility_mode_for(platform_version: str) -> str:
    """Map platform version to CompatibilityMode enum value."""
    parts = platform_version.split(".")
    if (
        len(parts) >= 3
        and parts[0].isdigit()
        and parts[1].isdigit()
        and parts[2].isdigit()
    ):
        return f"Version{parts[0]}_{parts[1]}_{parts[2]}"
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"Version{parts[0]}_{parts[1]}_0"
    return "Version8_3_27"


def _render(template: str, values: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"Неизвестный placeholder: {{{{{key}}}}}")
        return values[key]

    return _PLACEHOLDER_RE.sub(repl, template)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".xml":
        text = content.replace("\r\n", "\n").replace("\n", "\r\n").rstrip("\r\n")
        path.write_text(text, encoding="utf-8-sig", newline="")
    else:
        path.write_text(content, encoding="utf-8", newline="\n")


def _copy_rendered(
    src: Path,
    dest: Path,
    values: dict[str, str],
    *,
    created: list[str],
    root: Path,
) -> None:
    text = src.read_text(encoding="utf-8")
    if src.name.endswith(".tmpl"):
        text = _render(text, values)
        if dest.name.endswith(".tmpl"):
            dest = dest.with_name(dest.name[: -len(".tmpl")])
    _write_text(dest, text)
    created.append(str(dest.relative_to(root)))


def _placeholder_values(name: str, platform_version: str) -> dict[str, str]:
    return {
        "name": name,
        "synonym": name,
        "platform_version": platform_version,
        "compatibility_mode": compatibility_mode_for(platform_version),
        "uuid_cfg": str(uuid.uuid4()),
        "uuid_lang": str(uuid.uuid4()),
        **{f"uuid_co{i}": str(uuid.uuid4()) for i in range(7)},
    }


def _scaffold_configuration(
    target: Path,
    *,
    name: str,
    platform_version: str,
    force: bool,
) -> list[str]:
    tmpl_dir = templates_root() / "configuration"
    if not tmpl_dir.is_dir():
        raise FileNotFoundError(f"Шаблон configuration не найден: {tmpl_dir}")

    src_cfg = target / "src" / "cf" / "Configuration.xml"
    if src_cfg.exists() and not force:
        raise FileExistsError(f"Исходники конфигурации уже существуют: {src_cfg}")

    base = _placeholder_values(name, platform_version)
    yaml_values = base
    xml_values = {
        **base,
        "name": xml_escape(name),
        "synonym": xml_escape(name),
    }

    created: list[str] = []

    _copy_rendered(
        tmpl_dir / "1c.project.yaml.tmpl",
        target / MANIFEST_NAME,
        yaml_values,
        created=created,
        root=target,
    )
    _copy_rendered(
        tmpl_dir / "AGENTS.md",
        target / "AGENTS.md",
        yaml_values,
        created=created,
        root=target,
    )
    _copy_rendered(
        tmpl_dir / ".gitignore",
        target / ".gitignore",
        yaml_values,
        created=created,
        root=target,
    )

    cf_tmpl = tmpl_dir / "src" / "cf"
    for path in sorted(cf_tmpl.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(tmpl_dir)
        _copy_rendered(path, target / rel, xml_values, created=created, root=target)

    for directory in (
        target / "build",
        target / ".runtime",
        target / ".runtime" / "ib",
    ):
        directory.mkdir(parents=True, exist_ok=True)
        rel_dir = str(directory.relative_to(target))
        if rel_dir not in created:
            created.append(rel_dir)

    return created


def init_project(
    target: Path | None = None,
    *,
    project_type: str = "configuration",
    name: str | None = None,
    force: bool = False,
) -> ProjectResult:
    """Create a new project skeleton in target (default: CWD)."""
    root = (target or Path.cwd()).resolve()
    root.mkdir(parents=True, exist_ok=True)

    if project_type not in SUPPORTED_TYPES:
        return ProjectResult(
            status="error",
            root=root,
            diagnostics=[
                error(
                    f"Тип проекта не поддерживается в M1: {project_type}",
                    code="1CP005",
                    suggestion="Используйте --type configuration",
                )
            ],
        )

    manifest_path = root / MANIFEST_NAME
    if manifest_path.exists() and not force:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            diagnostics=[
                error(
                    f"Проект уже инициализирован: {MANIFEST_NAME}",
                    code="1CP004",
                    file=MANIFEST_NAME,
                    suggestion="Укажите --force для перезаписи или выберите другой каталог",
                )
            ],
        )

    project_name = sanitize_project_name(name) if name else default_project_name(root)
    discovery = discover_environment()
    platform_version = platform_version_for_manifest(discovery.platform.version)

    try:
        created = _scaffold_configuration(
            root,
            name=project_name,
            platform_version=platform_version,
            force=force,
        )
    except FileExistsError as exc:
        return ProjectResult(
            status="error",
            root=root,
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
            root=root,
            diagnostics=[
                error(
                    f"Ошибка инициализации проекта: {exc}",
                    code="1CP006",
                )
            ],
        )

    result = validate_project(root)
    result.created = created
    return result
