#!/usr/bin/env python3
"""Resolve agent profile → host checkout under OH_WORKSPACES_ROOT.

Used by docker-wrapper.sh at `docker run` time (inside Agent Canvas).

Preferred input: agent_profile_id from env OH_RUNTIME_LAUNCHED_PROFILE
(Canvas already injects it into `docker run -e …`).

Fallback: conversation UUID → GET /api/conversations/<id>.

Env:
  OH_INJECT_WORKSPACES_ROOT / OH_WORKSPACES_ROOT
  OH_DEFAULT_PROJECT
  LOCAL_BACKEND_API_KEY
  PORT / OPENHANDS_PORT / OH_API_BASE

Usage:
  resolve-oh-workspace.py --profile-id <uuid>
  resolve-oh-workspace.py --conversation-id <uuid>
  resolve-oh-workspace.py <conversation-id>   # legacy

Stdout: absolute host path to mount at /workspace
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def log(msg: str) -> None:
    print(f"[resolve-oh-workspace] {msg}", file=sys.stderr, flush=True)


def api(base: str, key: str, path: str) -> tuple[int, object]:
    headers = {"Accept": "application/json"}
    if key:
        headers["X-Session-API-Key"] = key
    req = urllib.request.Request(f"{base}{path}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw[:300]
        return e.code, payload
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def profile_name_by_id(base: str, key: str, profile_id: str) -> str | None:
    code, listing = api(base, key, "/api/agent-profiles")
    if code != 200 or not isinstance(listing, dict):
        log(f"WARN: list agent-profiles HTTP {code}: {listing}")
        return None
    for p in listing.get("profiles") or []:
        if isinstance(p, dict) and p.get("id") == profile_id:
            name = p.get("name")
            return name if isinstance(name, str) else None
    return None


def conversation_profile_id(base: str, key: str, conv_id: str) -> str | None:
    code, body = api(base, key, f"/api/conversations/{conv_id}")
    if code != 200 or not isinstance(body, dict):
        return None
    launched = body.get("launched_agent_profile")
    if isinstance(launched, dict):
        pid = launched.get("agent_profile_id")
        if isinstance(pid, str) and pid:
            return pid
    return None


def hyphenate_compact_uuid(value: str) -> str:
    """runtime-data dirs use UUID without dashes."""
    hex_only = value.replace("-", "")
    if len(hex_only) == 32 and all(c in "0123456789abcdefABCDEF" for c in hex_only):
        return (
            f"{hex_only[0:8]}-{hex_only[8:12]}-{hex_only[12:16]}-"
            f"{hex_only[16:20]}-{hex_only[20:32]}"
        )
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("conversation_id", nargs="?", default="")
    parser.add_argument("--profile-id", default="")
    parser.add_argument("--conversation-id", dest="conversation_id_opt", default="")
    args = parser.parse_args()

    profile_id = (args.profile_id or "").strip()
    conv_id = (args.conversation_id_opt or args.conversation_id or "").strip()
    if conv_id:
        conv_id = hyphenate_compact_uuid(conv_id)

    root = (
        os.environ.get("OH_INJECT_WORKSPACES_ROOT")
        or os.environ.get("OH_WORKSPACES_ROOT")
        or ""
    ).rstrip("/")
    default_slug = (os.environ.get("OH_DEFAULT_PROJECT") or "").strip()
    key = os.environ.get("LOCAL_BACKEND_API_KEY", "")
    port = os.environ.get("PORT") or os.environ.get("OPENHANDS_PORT") or "3000"
    base = (os.environ.get("OH_API_BASE") or f"http://127.0.0.1:{port}").rstrip("/")

    if not root:
        log("ERROR: OH_WORKSPACES_ROOT / OH_INJECT_WORKSPACES_ROOT is empty")
        return 1
    if not default_slug:
        log("ERROR: OH_DEFAULT_PROJECT is empty")
        return 1

    if not profile_id and conv_id:
        for _ in range(8):
            profile_id = conversation_profile_id(base, key, conv_id) or ""
            if profile_id:
                break
            time.sleep(0.1)

    slug = default_slug
    name: str | None = None
    if profile_id:
        name = profile_name_by_id(base, key, profile_id)
        if name and name != "default":
            slug = name
        log(
            f"profile_id={profile_id} name={name!r} conv={conv_id or '-'} → slug={slug}"
        )
    else:
        log(
            f"WARN: no profile id (conv={conv_id or '-'}); "
            f"using OH_DEFAULT_PROJECT={default_slug}"
        )

    path = f"{root}/{slug}"
    if not os.path.isdir(path):
        log(f"ERROR: project path is not a directory: {path}")
        return 1

    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
