#!/usr/bin/env python3
"""Seed Agent Canvas Settings at compose start (idempotent).

- Provider Connection + LLM profile (local openai-compatible)
- Agent profiles per project under OH_WORKSPACES_ROOT
- MCP: stdio 1c-dev + HTTP siblings (bsl-ls / v8std / mcp-atlassian)

Uses only stdlib (urllib). Runs in the openhands-bootstrap one-shot service.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

OH_API_BASE = os.environ.get("OH_API_BASE", "http://127.0.0.1:3000").rstrip("/")
WAIT_SECS = int(os.environ.get("WAIT_SECS", os.environ.get("MCP_BOOTSTRAP_WAIT_SECS", "180")))
SLEEP_SECS = float(os.environ.get("SLEEP_SECS", "2"))
API_KEY = os.environ.get("LOCAL_BACKEND_API_KEY", "")

LLM_PROVIDER_NAME = os.environ.get("LLM_PROVIDER_NAME", "local-openai")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/qwen3.8:27b")
LLM_PROFILE_NAME = os.environ.get("LLM_PROFILE_NAME", "local-qwen")
LLM_NATIVE = os.environ.get("LLM_NATIVE_TOOL_CALLING", "true").lower() in (
    "1",
    "true",
    "yes",
)
LLM_REASONING = os.environ.get("LLM_REASONING_EFFORT", "none")
LLM_MAX_IN = int(os.environ.get("LLM_MAX_INPUT_TOKENS", "210000"))
LLM_MAX_OUT = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "32000"))

MCP_HTTP_SERVERS = os.environ.get("MCP_HTTP_SERVERS", "bsl-ls,v8std,atlassian")
BSL_LS_URL = os.environ.get("MCP_BSL_LS_URL", "http://127.0.0.1:18767/mcp")
V8STD_URL = os.environ.get("MCP_V8STD_URL", "http://127.0.0.1:18766/mcp")
BSL_SEARCH_URL = os.environ.get("MCP_BSL_SEARCH_URL", "http://127.0.0.1:18005/mcp")
ATLASSIAN_URL = os.environ.get("MCP_ATLASSIAN_URL", "http://127.0.0.1:18768/mcp")

OH_WORKSPACES_ROOT = (os.environ.get("OH_WORKSPACES_ROOT") or "").rstrip("/")
OH_DEFAULT_PROJECT = (os.environ.get("OH_DEFAULT_PROJECT") or "").strip()
OH_PROJECT_SLUGS = (os.environ.get("OH_PROJECT_SLUGS") or "").strip()


def log(msg: str) -> None:
    print(f"[oh-bootstrap] {msg}", flush=True)


def api(
    method: str,
    path: str,
    body: Any | None = None,
) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["X-Session-API-Key"] = API_KEY
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{OH_API_BASE}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            payload: Any = json.loads(raw) if raw else None
            return resp.status, payload
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw[:500]
        return e.code, payload
    except Exception as e:  # noqa: BLE001 — bootstrap must not crash on net blips
        return 0, str(e)


def wait_ready() -> None:
    deadline = time.time() + WAIT_SECS
    last = 0
    while time.time() < deadline:
        code, _ = api("GET", "/api/settings")
        last = code
        if code == 200:
            log(f"Canvas API ready ({OH_API_BASE})")
            return
        time.sleep(SLEEP_SECS)
    log(f"ERROR: Canvas API not ready after {WAIT_SECS}s (last HTTP {last})")
    sys.exit(1)


def ensure_provider_connection() -> str | None:
    if not LLM_BASE_URL:
        log("LLM_BASE_URL empty — skip provider/profile seed")
        return None
    if not LLM_API_KEY:
        log("WARN: LLM_API_KEY empty — skip provider/profile seed (MCP still applied)")
        return None

    code, conns = api("GET", "/api/llm/provider-connections")
    if code != 200:
        log(f"ERROR: list provider-connections HTTP {code}: {conns}")
        return None
    if not isinstance(conns, list):
        conns = []

    for c in conns:
        if not isinstance(c, dict):
            continue
        name = (c.get("display_name") or "").strip()
        base = (c.get("base_url") or "").rstrip("/")
        if name == LLM_PROVIDER_NAME and base == LLM_BASE_URL:
            cid = c.get("id")
            log(f"Provider '{LLM_PROVIDER_NAME}' already ok — id={cid}")
            return str(cid) if cid else None

    body = {
        "display_name": LLM_PROVIDER_NAME,
        "provider": LLM_PROVIDER or "openai",
        "api_key": LLM_API_KEY,
        "base_url": LLM_BASE_URL,
    }
    code, created = api("POST", "/api/llm/provider-connections", body)
    if code not in (200, 201) or not isinstance(created, dict) or not created.get("id"):
        log(f"ERROR: create provider-connection HTTP {code}: {created}")
        return None
    log(f"Provider '{LLM_PROVIDER_NAME}' created (id={created['id']})")
    return str(created["id"])


def ensure_llm_profile(connection_id: str | None) -> None:
    if not connection_id and not LLM_API_KEY:
        return
    if not LLM_BASE_URL:
        return

    code, listing = api("GET", "/api/profiles")
    profiles = []
    if code == 200 and isinstance(listing, dict):
        profiles = listing.get("profiles") or []

    already = False
    for p in profiles:
        if not isinstance(p, dict):
            continue
        if p.get("name") != LLM_PROFILE_NAME:
            continue
        if p.get("model") == LLM_MODEL and (p.get("base_url") or "").rstrip("/") in (
            LLM_BASE_URL,
            "",
        ):
            # Linked connection hides base_url on profile list sometimes —
            # still OK if name+model match
            already = True
            break
        if p.get("model") == LLM_MODEL:
            already = True
            break

    llm: dict[str, Any] = {
        "model": LLM_MODEL,
        "auth_type": "api_key",
        "native_tool_calling": LLM_NATIVE,
        "reasoning_effort": LLM_REASONING,
        "max_input_tokens": LLM_MAX_IN,
        "max_output_tokens": LLM_MAX_OUT,
        "drop_params": True,
    }
    if connection_id:
        llm["provider_connection_id"] = connection_id
    else:
        llm["api_key"] = LLM_API_KEY
        llm["base_url"] = LLM_BASE_URL

    if already:
        log(f"LLM profile '{LLM_PROFILE_NAME}' already present — refresh + activate")
    else:
        log(f"Creating LLM profile '{LLM_PROFILE_NAME}'")

    code, resp = api("POST", f"/api/profiles/{LLM_PROFILE_NAME}", {"llm": llm})
    if code not in (200, 201):
        log(f"ERROR: save profile HTTP {code}: {resp}")
        return
    log(f"LLM profile '{LLM_PROFILE_NAME}' saved (HTTP {code})")

    code, resp = api("POST", f"/api/profiles/{LLM_PROFILE_NAME}/activate", {})
    if code != 200:
        log(f"WARN: activate profile HTTP {code}: {resp}")
    else:
        log(f"LLM profile '{LLM_PROFILE_NAME}' activated")


def mcp_entry(settings: dict[str, Any], key: str) -> dict[str, Any] | None:
    # Settings shapes vary; search mcp_config under agent_settings or top-level.
    candidates: list[Any] = [
        settings.get("mcp_config"),
        (settings.get("agent_settings") or {}).get("mcp_config")
        if isinstance(settings.get("agent_settings"), dict)
        else None,
    ]
    for cfg in candidates:
        if isinstance(cfg, dict) and key in cfg and isinstance(cfg[key], dict):
            return cfg[key]
    return None


def mcp_ok(settings: dict[str, Any], key: str, marker: str) -> bool:
    entry = mcp_entry(settings, key)
    if not entry:
        return False
    if entry.get("enabled") is False:
        return False
    blob = json.dumps(entry, ensure_ascii=False)
    return marker in blob


def upsert_mcp(key: str, body: dict[str, Any], marker: str) -> None:
    code, settings = api("GET", "/api/settings")
    if code != 200 or not isinstance(settings, dict):
        log(f"ERROR: GET settings before MCP '{key}' HTTP {code}")
        return
    if mcp_ok(settings, key, marker):
        log(f"MCP '{key}' already ok — skip")
        return

    if mcp_entry(settings, key) is not None:
        log(f"Replacing MCP '{key}'")
        api("DELETE", f"/api/settings/mcp/{key}")

    log(f"Creating MCP '{key}'")
    code, resp = api("POST", f"/api/settings/mcp/{key}", body)
    if code in (200, 201):
        log(f"MCP '{key}' created (HTTP {code})")
        return

    log(f"Create HTTP {code}; trying PATCH merge")
    patch = {"agent_settings_diff": {"mcp_config": {key: body}}}
    code, resp = api("PATCH", "/api/settings", patch)
    if code != 200:
        log(f"ERROR: upsert '{key}' failed HTTP {code}: {resp}")
        return
    log(f"MCP '{key}' upserted via PATCH")



def ensure_agent_profile_llm_ref() -> None:
    """Point agent profile 'default' at LLM_PROFILE_NAME (required after fresh data)."""
    code, listing = api("GET", "/api/agent-profiles")
    if code != 200 or not isinstance(listing, dict):
        log(f"WARN: list agent-profiles HTTP {code}: {listing}")
        return
    profiles = listing.get("profiles") or []
    target = None
    for p in profiles:
        if isinstance(p, dict) and p.get("name") == "default":
            target = p
            break
    if not target and profiles:
        target = profiles[0]
    if not target:
        log("WARN: no agent profile to link LLM")
        return
    name = target.get("name") or "default"
    code, detail = api("GET", f"/api/agent-profiles/{name}")
    if code != 200 or not isinstance(detail, dict):
        log(f"WARN: get agent-profile '{name}' HTTP {code}")
        return
    prof = detail.get("profile") if isinstance(detail.get("profile"), dict) else detail
    if not isinstance(prof, dict):
        log("WARN: unexpected agent-profile shape")
        return
    if prof.get("llm_profile_ref") == LLM_PROFILE_NAME:
        log(f"Agent profile '{name}' already → LLM '{LLM_PROFILE_NAME}'")
        return
    prof = dict(prof)
    prof["llm_profile_ref"] = LLM_PROFILE_NAME
    code, resp = api("POST", f"/api/agent-profiles/{name}", prof)
    if code not in (200, 201):
        log(f"ERROR: save agent-profile HTTP {code}: {resp}")
        return
    log(f"Agent profile '{name}' → LLM '{LLM_PROFILE_NAME}'")


def list_project_slugs() -> list[str]:
    """Subdirs under OH_WORKSPACES_ROOT that become agent profiles."""
    if not OH_WORKSPACES_ROOT:
        log("WARN: OH_WORKSPACES_ROOT unset — skip project agent profiles")
        return []
    if not os.path.isdir(OH_WORKSPACES_ROOT):
        log(f"WARN: OH_WORKSPACES_ROOT not a directory: {OH_WORKSPACES_ROOT}")
        return []

    allow: set[str] | None = None
    if OH_PROJECT_SLUGS:
        allow = {s.strip() for s in OH_PROJECT_SLUGS.split(",") if s.strip()}

    slugs: list[str] = []
    try:
        names = sorted(os.listdir(OH_WORKSPACES_ROOT))
    except OSError as exc:
        log(f"WARN: cannot list {OH_WORKSPACES_ROOT}: {exc}")
        return []

    for name in names:
        if name.startswith("."):
            continue
        path = os.path.join(OH_WORKSPACES_ROOT, name)
        if not os.path.isdir(path):
            continue
        if allow is not None and name not in allow:
            continue
        # Prefer real checkouts; still allow allowlisted dirs without .git.
        if allow is None and not os.path.isdir(os.path.join(path, ".git")):
            continue
        if name == "default":
            log("WARN: skip project dir named 'default' (reserved agent profile)")
            continue
        slugs.append(name)
    return slugs


def project_system_suffix(slug: str) -> str:
    return (
        f"You are working on project '{slug}'. "
        f"The git checkout is mounted at /workspace (read-write). "
        f"Do not access other host projects. "
        f"For BSL Language Server MCP call register_workspace_folder("
        f'"/workspaces/{slug}") before diagnostics.'
    )


def ensure_project_agent_profiles() -> None:
    """Create/update one agent profile per project slug under OH_WORKSPACES_ROOT."""
    slugs = list_project_slugs()
    if not slugs:
        log("No project slugs to seed as agent profiles")
        return

    code, detail = api("GET", "/api/agent-profiles/default")
    base: dict[str, Any] = {}
    if code == 200 and isinstance(detail, dict):
        prof = detail.get("profile") if isinstance(detail.get("profile"), dict) else detail
        if isinstance(prof, dict):
            base = dict(prof)

    for slug in slugs:
        suffix = project_system_suffix(slug)
        body: dict[str, Any] = {
            "name": slug,
            "agent_kind": base.get("agent_kind") or "openhands",
            "llm_profile_ref": LLM_PROFILE_NAME,
            "system_message_suffix": suffix,
        }
        for key in ("condenser", "verification", "agent", "tools", "persona"):
            if key in base and base[key] is not None:
                body[key] = base[key]

        # Idempotent: refresh suffix / llm ref if profile already exists.
        code_get, existing = api("GET", f"/api/agent-profiles/{slug}")
        if code_get == 200 and isinstance(existing, dict):
            cur = (
                existing.get("profile")
                if isinstance(existing.get("profile"), dict)
                else existing
            )
            if isinstance(cur, dict):
                merged = dict(cur)
                merged["llm_profile_ref"] = LLM_PROFILE_NAME
                merged["system_message_suffix"] = suffix
                merged["name"] = slug
                body = merged

        code_save, resp = api("POST", f"/api/agent-profiles/{slug}", body)
        if code_save not in (200, 201):
            log(f"ERROR: save agent-profile '{slug}' HTTP {code_save}: {resp}")
            continue
        log(f"Agent profile '{slug}' ready (workspace /workspaces/{slug})")

    if OH_DEFAULT_PROJECT and OH_DEFAULT_PROJECT not in slugs:
        log(
            f"WARN: OH_DEFAULT_PROJECT={OH_DEFAULT_PROJECT!r} not in seeded slugs "
            f"{slugs}"
        )
    log(f"OK: project agent profiles: {', '.join(slugs)}")


def seed_mcp() -> None:
    upsert_mcp(
        "1c-dev",
        {
            "transport": "stdio",
            "command": "1c-dev",
            "args": ["mcp"],
            "description": "1c-dev toolchain MCP (stdio inside conversation /workspace)",
            "enabled": True,
        },
        '"1c-dev"',
    )

    mapping = {
        "bsl-ls": (
            "bsl-language-server",
            {
                "transport": "streamable-http",
                "url": BSL_LS_URL,
                "description": "BSL LS (sibling compose service bsl-ls)",
                "enabled": True,
            },
            BSL_LS_URL,
        ),
        "bsl-language-server": (
            "bsl-language-server",
            {
                "transport": "streamable-http",
                "url": BSL_LS_URL,
                "description": "BSL LS (sibling compose service bsl-ls)",
                "enabled": True,
            },
            BSL_LS_URL,
        ),
        "v8std": (
            "v8std",
            {
                "transport": "streamable-http",
                "url": V8STD_URL,
                "description": "v8std MCP (sibling compose)",
                "enabled": True,
            },
            V8STD_URL,
        ),
        "bsl-search": (
            "bsl-search",
            {
                "transport": "streamable-http",
                "url": BSL_SEARCH_URL,
                "description": "bsl-search MCP (sibling compose, profile mcp-search)",
                "enabled": True,
            },
            BSL_SEARCH_URL,
        ),
        "atlassian": (
            "mcp-atlassian",
            {
                "transport": "streamable-http",
                "url": ATLASSIAN_URL,
                "description": "Jira/Confluence MCP (sibling compose mcp-atlassian)",
                "enabled": True,
            },
            ATLASSIAN_URL,
        ),
        "mcp-atlassian": (
            "mcp-atlassian",
            {
                "transport": "streamable-http",
                "url": ATLASSIAN_URL,
                "description": "Jira/Confluence MCP (sibling compose mcp-atlassian)",
                "enabled": True,
            },
            ATLASSIAN_URL,
        ),
    }

    for raw in MCP_HTTP_SERVERS.split(","):
        name = raw.strip()
        if not name:
            continue
        if name not in mapping:
            log(f"WARN: unknown MCP_HTTP_SERVERS entry '{name}' — skip")
            continue
        key, body, marker = mapping[name]
        upsert_mcp(key, body, marker)

    log(f"OK: seeded MCP (stdio 1c-dev + HTTP: {MCP_HTTP_SERVERS})")
    log("NOTE: conversation needs compose network (docker-wrapper); use a NEW chat")


def main() -> int:
    wait_ready()
    conn_id = ensure_provider_connection()
    ensure_llm_profile(conn_id)
    ensure_agent_profile_llm_ref()
    ensure_project_agent_profiles()
    seed_mcp()
    return 0


if __name__ == "__main__":
    sys.exit(main())
