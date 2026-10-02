"""Idempotent IDE configure: AGENTS, gitignore, IDE MCP + rules (ADR-016 / #50 / #90)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from adapters.platform import discover_environment
from adapters.source.xmlgen.resolve import resolve_java
from core.diagnostics import Diagnostic, error, warning
from core.project.constants import (
    DEFAULT_CONFIG_ID,
    DEFAULT_RUNTIME_ID,
    HOME_MANIFEST_REL,
    HOME_RUNTIME_DIR_NAME,
)
from core.project.init import (
    default_project_name,
    platform_version_for_manifest,
    templates_root,
)
from core.project.paths import home_manifest_path, project_home
from core.project.result import ProjectResult
from core.project.validate import validate_project
from core.toolchain.cache import tools_cache_dir
from core.toolchain.manifest import load_manifest
from core.toolchain.resolve import resolve_component_jar

IdeName = Literal["cursor", "kilocode"]
AgentsMode = Literal["auto", "scope", "none"]

SUPPORTED_TARGETS: frozenset[str] = frozenset({"all", "cursor", "kilocode", "none"})
SUPPORTED_AGENTS: frozenset[str] = frozenset({"auto", "scope", "none"})

AGENTS_BEGIN = "<!-- BEGIN 1c-dev -->"
AGENTS_END = "<!-- END 1c-dev -->"

RULES_MANAGED_BY = "1c-dev"
RULES_MD_MARKER = f"<!-- managed-by: {RULES_MANAGED_BY} -->"

_IDE_MCP_REL: dict[IdeName, str] = {
    "cursor": ".cursor/mcp.json",
    "kilocode": ".kilo/mcp.json",
}

_IDE_RULES_REL: dict[IdeName, str] = {
    "cursor": ".cursor/rules",
    "kilocode": ".kilo/rules",
}

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


@dataclass(frozen=True)
class RuleSpec:
    """One IDE rule shipped by 1c-dev (id + title + markdown body)."""

    id: str
    title: str
    body: str


def ides_to_configure(target: str) -> list[IdeName]:
    """Map --target value to concrete IDE list."""
    if target == "all":
        return ["cursor", "kilocode"]
    if target == "cursor":
        return ["cursor"]
    if target == "kilocode":
        return ["kilocode"]
    if target == "none":
        return []
    raise ValueError(target)


def mcp_rel_path(ide: IdeName) -> str:
    """Relative path of MCP config for IDE."""
    return _IDE_MCP_REL[ide]


def rules_dir_rel(ide: IdeName) -> str:
    """Relative directory of IDE rules for IDE."""
    return _IDE_RULES_REL[ide]


def rule_file_rel(ide: IdeName, rule_id: str) -> str:
    """Relative path of a single rule file for IDE."""
    suffix = ".mdc" if ide == "cursor" else ".md"
    return f"{rules_dir_rel(ide)}/{rule_id}{suffix}"


def _should_write_agents(agents: str, project: Path, ide_root: Path) -> bool:
    if agents == "none":
        return False
    if agents == "scope":
        return True
    return project == ide_root


def _render(template: str, values: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"Неизвестный placeholder: {{{{{key}}}}}")
        return values[key]

    return _PLACEHOLDER_RE.sub(repl, template)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _ensure_manifest(root: Path) -> list[str]:
    """Create ``.1c-dev/project.yaml`` + runtime dirs if missing. Never overwrite."""
    created: list[str] = []
    manifest_path = home_manifest_path(root)
    if not manifest_path.is_file():
        tmpl = templates_root() / "configuration" / "1c.project.yaml.tmpl"
        if not tmpl.is_file():
            raise FileNotFoundError(f"Шаблон манифеста не найден: {tmpl}")
        discovery = discover_environment()
        platform_version = platform_version_for_manifest(discovery.platform.version)
        name = default_project_name(root)
        project_home(root).mkdir(parents=True, exist_ok=True)
        text = _render(
            tmpl.read_text(encoding="utf-8"),
            {
                "name": name,
                "platform_version": platform_version,
                "config_id": DEFAULT_CONFIG_ID,
                "runtime_id": DEFAULT_RUNTIME_ID,
            },
        )
        _write_text(manifest_path, text)
        created.append(HOME_MANIFEST_REL)

    for directory in (
        root / HOME_RUNTIME_DIR_NAME,
        root / HOME_RUNTIME_DIR_NAME / DEFAULT_CONFIG_ID,
        root / "build",
    ):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(str(directory.relative_to(root)))

    return created


def _merge_gitignore(
    root: Path,
    *,
    force: bool,
) -> tuple[list[str], list[str], list[str]]:
    """Return (created, updated, skipped) relative paths."""
    tmpl = templates_root() / "configuration" / ".gitignore"
    template_text = tmpl.read_text(encoding="utf-8")
    if not template_text.endswith("\n"):
        template_text += "\n"
    dest = root / ".gitignore"
    rel = ".gitignore"

    if not dest.is_file():
        _write_text(dest, template_text)
        return [rel], [], []

    if force:
        _write_text(dest, template_text)
        return [], [rel], []

    existing_lines = dest.read_text(encoding="utf-8").splitlines()
    existing_set = {line.strip() for line in existing_lines if line.strip()}
    to_append: list[str] = []
    for line in template_text.splitlines():
        stripped = line.strip()
        if stripped and stripped not in existing_set:
            to_append.append(line)

    if not to_append:
        return [], [], [rel]

    new_content = dest.read_text(encoding="utf-8")
    if new_content and not new_content.endswith("\n"):
        new_content += "\n"
    new_content += "\n".join(to_append) + "\n"
    _write_text(dest, new_content)
    return [], [rel], []


def _agents_template_text() -> str:
    tmpl = templates_root() / "configuration" / "AGENTS.md"
    template_text = tmpl.read_text(encoding="utf-8")
    if not template_text.endswith("\n"):
        template_text += "\n"
    return template_text


def _upsert_agents_block(existing: str, block: str) -> str:
    """Insert or replace the managed 1c-dev block; preserve surrounding text."""
    begin_idx = existing.find(AGENTS_BEGIN)
    end_idx = existing.find(AGENTS_END)
    block_body = block.rstrip("\n") + "\n"

    if begin_idx == -1 or end_idx == -1 or end_idx < begin_idx:
        base = existing
        if base and not base.endswith("\n"):
            base += "\n"
        if base and not base.endswith("\n\n"):
            base += "\n"
        return base + block_body

    end_pos = end_idx + len(AGENTS_END)
    if end_pos < len(existing) and existing[end_pos] == "\n":
        end_pos += 1
    return existing[:begin_idx] + block_body + existing[end_pos:]


def _merge_agents(
    root: Path,
    *,
    force: bool,
) -> tuple[list[str], list[str], list[str], list[Diagnostic]]:
    """Create or merge managed AGENTS.md block. Return (created, updated, skipped, diags)."""
    template_text = _agents_template_text()
    dest = root / "AGENTS.md"
    rel = "AGENTS.md"
    diagnostics: list[Diagnostic] = []

    if not dest.is_file():
        _write_text(dest, template_text)
        return [rel], [], [], diagnostics

    if force:
        _write_text(dest, template_text)
        return [], [rel], [], diagnostics

    existing = dest.read_text(encoding="utf-8")
    merged = _upsert_agents_block(existing, template_text)
    if merged == existing:
        return [], [], [rel], diagnostics

    _write_text(dest, merged)
    return [], [rel], [], diagnostics


def build_mcp_servers_payload(
    *,
    jar_path: Path,
    java_command: str,
) -> dict[str, Any]:
    """Template mcpServers block (no cwd)."""
    return {
        "1c-dev": {
            "command": "1c-dev",
            "args": ["mcp"],
        },
        "bsl-language-server": {
            "command": java_command,
            "args": ["-jar", str(jar_path), "mcp"],
        },
    }


def _resolve_bsl_jar() -> tuple[Path, bool]:
    """Return (absolute jar path, found). Missing → expected stable cache path."""
    manifest = load_manifest()
    spec = manifest.get("bsl-language-server")
    if spec is None:
        return (tools_cache_dir() / "bsl-language-server.jar").resolve(), False
    resolved = resolve_component_jar(spec)
    if resolved.path is not None:
        path = resolved.path.expanduser()
        if resolved.found:
            return path.resolve(), True
        return path if path.is_absolute() else path.resolve(), False
    return (tools_cache_dir() / spec.artifact).resolve(), False


def _java_command() -> str:
    java = resolve_java()
    if java.found and java.path is not None:
        return str(java.path)
    return "java"


def _configure_ide_mcp(
    root: Path,
    ides: list[IdeName],
    *,
    force: bool,
) -> tuple[list[str], list[str], list[str], list[Diagnostic]]:
    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    diagnostics: list[Diagnostic] = []

    if not ides:
        return created, updated, skipped, diagnostics

    jar_path, jar_found = _resolve_bsl_jar()
    if not jar_found:
        diagnostics.append(
            warning(
                "bsl-language-server jar не найден — в MCP прописан ожидаемый путь cache",
                code="1CP009",
                suggestion="Выполните 1c-dev tools sync или задайте ONEC_BSLLS_JAR",
            )
        )

    servers = build_mcp_servers_payload(
        jar_path=jar_path,
        java_command=_java_command(),
    )

    for ide in ides:
        rel = mcp_rel_path(ide)
        dest = root / rel
        existed = dest.is_file()

        if force or not existed:
            payload = {"mcpServers": dict(servers)}
            _write_text(dest, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            if existed:
                updated.append(rel)
            else:
                created.append(rel)
            continue

        try:
            data = json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"mcpServers": dict(servers)}
            _write_text(dest, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            updated.append(rel)
            continue

        if not isinstance(data, dict):
            payload = {"mcpServers": dict(servers)}
            _write_text(dest, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            updated.append(rel)
            continue

        existing = data.get("mcpServers")
        if not isinstance(existing, dict):
            existing = {}
            data["mcpServers"] = existing

        changed = False
        for name, server in servers.items():
            if name not in existing:
                existing[name] = server
                changed = True

        if not changed:
            skipped.append(rel)
            continue

        _write_text(dest, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        updated.append(rel)

    return created, updated, skipped, diagnostics


def _normalize_rule_body(body: str) -> str:
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n") + "\n"


def _load_rules_pack() -> list[RuleSpec]:
    """Load IDE rules shipped by 1c-dev from templates/configuration/rules."""
    rules_root = templates_root() / "configuration" / "rules"
    manifest_path = rules_root / "rules.manifest.yaml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Манифест IDE rules не найден: {manifest_path}")

    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
        raise ValueError(f"Некорректный манифест IDE rules: {manifest_path}")

    specs: list[RuleSpec] = []
    for entry in raw["rules"]:
        if not isinstance(entry, dict):
            raise ValueError(f"Некорректная запись в манифесте IDE rules: {entry!r}")
        rule_id = entry.get("id")
        title = entry.get("title")
        if not isinstance(rule_id, str) or not rule_id:
            raise ValueError(f"В манифесте IDE rules отсутствует id: {entry!r}")
        if not isinstance(title, str) or not title:
            raise ValueError(f"В манифесте IDE rules отсутствует title: {entry!r}")
        body_path = rules_root / f"{rule_id}.md"
        if not body_path.is_file():
            raise FileNotFoundError(f"Тело IDE rule не найдено: {body_path}")
        specs.append(
            RuleSpec(
                id=rule_id,
                title=title,
                body=_normalize_rule_body(body_path.read_text(encoding="utf-8")),
            )
        )
    return specs


def render_cursor_rule(spec: RuleSpec) -> str:
    """Render Cursor .mdc content (frontmatter + body)."""
    return (
        "---\n"
        f"description: {spec.title}\n"
        "alwaysApply: true\n"
        f"managedBy: {RULES_MANAGED_BY}\n"
        "---\n"
        "\n"
        f"{spec.body}"
    )


def render_kilocode_rule(spec: RuleSpec) -> str:
    """Render Kilocode .md content (managed marker + body)."""
    return f"{RULES_MD_MARKER}\n\n{spec.body}"


def _is_managed_cursor_rule(text: str) -> bool:
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return False
    frontmatter = text[3:end]
    return re.search(
        rf"(?m)^managedBy:\s*{re.escape(RULES_MANAGED_BY)}\s*$",
        frontmatter,
    ) is not None


def _is_managed_kilocode_rule(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped == RULES_MD_MARKER
    return False


def _configure_ide_rules(
    root: Path,
    ides: list[IdeName],
    *,
    force: bool,
) -> tuple[list[str], list[str], list[str], list[Diagnostic]]:
    """Write 1c-dev IDE rules under ide-root. Return created/updated/skipped/diags.

    ``force`` kept for API parity with MCP configure; foreign same-name files are
    never overwritten (managed updates happen whenever content differs).
    """
    del force  # foreign files are never overwritten; see docstring
    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    diagnostics: list[Diagnostic] = []

    if not ides:
        return created, updated, skipped, diagnostics

    specs = _load_rules_pack()
    renders: dict[IdeName, dict[str, str]] = {
        "cursor": {spec.id: render_cursor_rule(spec) for spec in specs},
        "kilocode": {spec.id: render_kilocode_rule(spec) for spec in specs},
    }

    for ide in ides:
        for spec in specs:
            rel = rule_file_rel(ide, spec.id)
            dest = root / rel
            desired = renders[ide][spec.id]
            existed = dest.is_file()

            if not existed:
                _write_text(dest, desired)
                created.append(rel)
                continue

            existing = dest.read_text(encoding="utf-8")
            is_managed = (
                _is_managed_cursor_rule(existing)
                if ide == "cursor"
                else _is_managed_kilocode_rule(existing)
            )

            if not is_managed:
                skipped.append(rel)
                diagnostics.append(
                    warning(
                        f"Пропущен чужой IDE rule (нет managed-маркера): {rel}",
                        code="1CP011",
                        file=rel,
                        suggestion=(
                            "Переименуйте файл или удалите его вручную, "
                            "чтобы установить правило из 1c-dev"
                        ),
                    )
                )
                continue

            if existing == desired:
                skipped.append(rel)
                continue

            _write_text(dest, desired)
            updated.append(rel)

    return created, updated, skipped, diagnostics


def configure_ide(
    path: Path | None = None,
    *,
    ide_root: Path | None = None,
    target: str = "all",
    force: bool = False,
    agents: str = "auto",
) -> ProjectResult:
    """
    Idempotent configure of agent/IDE artifacts in an existing project directory.

    ``path`` / project = scope root (manifest, gitignore, AGENTS).
    ``ide_root`` = where to write ``.cursor`` / ``.kilo`` (default = project).
    """
    project = (path or Path.cwd()).resolve()
    project.mkdir(parents=True, exist_ok=True)
    resolved_ide_root = (ide_root or project).resolve()
    resolved_ide_root.mkdir(parents=True, exist_ok=True)

    if target not in SUPPORTED_TARGETS:
        return ProjectResult(
            status="error",
            root=project,
            ide_root=resolved_ide_root,
            diagnostics=[
                error(
                    f"Неизвестное значение --target: {target}",
                    code="1CP007",
                    suggestion="Используйте all, cursor, kilocode или none",
                )
            ],
        )

    if agents not in SUPPORTED_AGENTS:
        return ProjectResult(
            status="error",
            root=project,
            ide_root=resolved_ide_root,
            diagnostics=[
                error(
                    f"Неизвестное значение --agents: {agents}",
                    code="1CP010",
                    suggestion="Используйте auto, scope или none",
                )
            ],
        )

    ides = ides_to_configure(target)

    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    diagnostics: list[Diagnostic] = []

    try:
        created.extend(_ensure_manifest(project))

        if _should_write_agents(agents, project, resolved_ide_root):
            a_c, a_u, a_s, a_d = _merge_agents(project, force=force)
            created.extend(a_c)
            updated.extend(a_u)
            skipped.extend(a_s)
            diagnostics.extend(a_d)

        g_c, g_u, g_s = _merge_gitignore(project, force=force)
        created.extend(g_c)
        updated.extend(g_u)
        skipped.extend(g_s)

        m_c, m_u, m_s, m_d = _configure_ide_mcp(
            resolved_ide_root, ides, force=force
        )
        created.extend(m_c)
        updated.extend(m_u)
        skipped.extend(m_s)
        diagnostics.extend(m_d)

        r_c, r_u, r_s, r_d = _configure_ide_rules(
            resolved_ide_root, ides, force=force
        )
        created.extend(r_c)
        updated.extend(r_u)
        skipped.extend(r_s)
        diagnostics.extend(r_d)
    except (OSError, FileNotFoundError, KeyError, ValueError) as exc:
        return ProjectResult(
            status="error",
            root=project,
            ide_root=resolved_ide_root,
            diagnostics=[
                error(
                    f"Ошибка настройки IDE проекта: {exc}",
                    code="1CP006",
                )
            ],
        )

    result = validate_project(project)
    result.ide_root = resolved_ide_root
    result.created = created
    result.updated = updated
    result.skipped = skipped
    result.diagnostics = [*diagnostics, *result.diagnostics]
    return result
