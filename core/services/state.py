"""Persist managed stack state under XDG share (ADR-033 Этап 2)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.tools.paths import services_share_dir

STATE_VERSION = 1
STATE_FILENAME = "state.json"


@dataclass
class StackState:
    """Record for one managed compose stack."""

    tool_id: str
    project_name: str
    last_action: str
    last_status: str
    healthy: bool | None = None
    running: bool | None = None
    health_url: str | None = None
    mcp_url: str | None = None
    updated_at: str = ""
    labels: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StackState:
        labels_raw = data.get("labels") or {}
        labels = (
            {str(k): str(v) for k, v in labels_raw.items()}
            if isinstance(labels_raw, dict)
            else {}
        )
        return cls(
            tool_id=str(data.get("toolId") or data.get("tool_id") or ""),
            project_name=str(data.get("projectName") or data.get("project_name") or ""),
            last_action=str(data.get("lastAction") or data.get("last_action") or ""),
            last_status=str(data.get("lastStatus") or data.get("last_status") or ""),
            healthy=data.get("healthy"),
            running=data.get("running"),
            health_url=data.get("healthUrl") or data.get("health_url"),
            mcp_url=data.get("mcpUrl") or data.get("mcp_url"),
            updated_at=str(data.get("updatedAt") or data.get("updated_at") or ""),
            labels=labels,
        )


def state_path(*, env: dict[str, str] | None = None, platform: str | None = None) -> Path:
    return services_share_dir(env=env, platform=platform) / STATE_FILENAME


def load_state(
    *, env: dict[str, str] | None = None, platform: str | None = None
) -> dict[str, StackState]:
    path = state_path(env=env, platform=platform)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    stacks = raw.get("stacks")
    if not isinstance(stacks, dict):
        return {}
    out: dict[str, StackState] = {}
    for key, value in stacks.items():
        if isinstance(value, dict):
            stack = StackState.from_dict(value)
            out[str(key)] = stack
    return out


def save_stack(
    stack: StackState,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    """Upsert one stack record and write state.json atomically."""
    if not stack.updated_at:
        stack.updated_at = datetime.now(UTC).isoformat()
    root = services_share_dir(env=env, platform=platform)
    root.mkdir(parents=True, exist_ok=True)
    path = root / STATE_FILENAME
    existing = load_state(env=env, platform=platform)
    existing[stack.tool_id] = stack
    payload = {
        "version": STATE_VERSION,
        "stacks": {
            tool_id: {
                "toolId": s.tool_id,
                "projectName": s.project_name,
                "lastAction": s.last_action,
                "lastStatus": s.last_status,
                "healthy": s.healthy,
                "running": s.running,
                "healthUrl": s.health_url,
                "mcpUrl": s.mcp_url,
                "updatedAt": s.updated_at,
                "labels": s.labels,
            }
            for tool_id, s in sorted(existing.items())
        },
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def remove_stack(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> None:
    existing = load_state(env=env, platform=platform)
    if tool_id not in existing:
        return
    del existing[tool_id]
    root = services_share_dir(env=env, platform=platform)
    root.mkdir(parents=True, exist_ok=True)
    path = root / STATE_FILENAME
    payload = {
        "version": STATE_VERSION,
        "stacks": {
            tid: {
                "toolId": s.tool_id,
                "projectName": s.project_name,
                "lastAction": s.last_action,
                "lastStatus": s.last_status,
                "healthy": s.healthy,
                "running": s.running,
                "healthUrl": s.health_url,
                "mcpUrl": s.mcp_url,
                "updatedAt": s.updated_at,
                "labels": s.labels,
            }
            for tid, s in sorted(existing.items())
        },
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


MANAGED_BY_LABEL = "managed-by=1c-dev"
TOOL_LABEL_PREFIX = "com.1c-dev.tool="


def default_stack_labels(tool_id: str) -> dict[str, str]:
    return {
        "managed-by": "1c-dev",
        "com.1c-dev.tool": tool_id,
    }
