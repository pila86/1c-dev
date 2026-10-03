#!/usr/bin/env python3
"""Spike #119: ручной запуск YaXUnit `RunUnitTests` и разбор jUnit-отчёта.

Не часть продукта; прототип для ADR-029 / adapters/test_yaxunit.

Пример (из каталога собранного проекта, где уже есть file IB):

    python run_yaxunit.py --ib .1c-dev/runtime/main --out /tmp/yax \
        --filter '{"extensions": ["Tests1"]}'
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

PLATFORM_ROOT = Path("/opt/1cv8/x86_64")
STATUS = {"failure": "failed", "error": "error", "skipped": "skipped"}


def find_1cv8() -> str:
    """Последняя установленная платформа (spike: только Linux)."""
    versions = sorted(p for p in PLATFORM_ROOT.iterdir() if (p / "1cv8").exists())
    if not versions:
        sys.exit("1cv8 не найден")
    return str(versions[-1] / "1cv8")


def build_config(out: Path, flt: dict[str, Any]) -> dict[str, Any]:
    return {
        "filter": flt,
        "reportFormat": "jUnit",
        "reportPath": str(out / "junit.xml"),
        "exitCode": str(out / "exit-code.txt"),
        "closeAfterTests": True,  # иначе 1cv8 не завершится
        "showReport": False,
        "logging": {"file": str(out / "yaxunit.log"), "console": False, "level": "debug"},
    }


def run(ib: Path, out: Path, flt: dict[str, Any], timeout: int) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for name in ("junit.xml", "exit-code.txt", "yaxunit.log", "out.log"):
        (out / name).unlink(missing_ok=True)
    cfg_path = out / "cfg.json"
    cfg_path.write_text(json.dumps(build_config(out, flt), ensure_ascii=False, indent=2))
    argv = [
        find_1cv8(),
        "ENTERPRISE",
        f"/F{ib.resolve()}",
        "/DisableStartupDialogs",
        "/DisableStartupMessages",
        "/DisableSplash",
        "/L",
        "ru",
        "/Out",
        str(out / "out.log"),
        f"/CRunUnitTests={cfg_path}",
    ]
    if not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
        argv = ["xvfb-run", "-a", *argv]
    # новая группа процессов: при timeout убиваем и xvfb-run, и 1cv8
    proc = subprocess.Popen(argv, start_new_session=True)
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        print(f"TIMEOUT {timeout}s", file=sys.stderr)
        return 124


def parse_junit(path: Path) -> list[dict[str, Any]]:
    """jUnit -> список тестов: extension (package), module, suite, test, status, message."""
    tests: list[dict[str, Any]] = []
    for suite in ET.parse(path).getroot().iter("testsuite"):
        for case in suite.findall("testcase"):
            status, message = "passed", ""
            for child in case:
                if child.tag in STATUS:
                    status = STATUS[child.tag]
                    message = child.get("message", "")
            tests.append(
                {
                    "extension": suite.get("package"),
                    "module": suite.get("classname"),
                    "suite": suite.get("name"),
                    "test": case.get("name"),
                    "context": case.get("context"),
                    "time": float(case.get("time", "0")),
                    "status": status,
                    "message": message,
                }
            )
    return tests


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ib", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--filter", default="{}", help="JSON для config.filter")
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args()

    rc = run(args.ib, args.out, json.loads(args.filter), args.timeout)
    junit = args.out / "junit.xml"
    result: dict[str, Any] = {"processExitCode": rc, "report": str(junit)}
    code_file = args.out / "exit-code.txt"
    if code_file.exists():
        result["yaxunitExitCode"] = int(code_file.read_text(encoding="utf-8-sig").strip())
    result["tests"] = parse_junit(junit) if junit.exists() else None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
