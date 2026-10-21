"""core.debug: breakpoints и инспекция стека/переменных (mocks)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from adapters.debug_http import (
    PROPERTY_ID_COMMON_MODULE,
    BreakpointSpec,
    DebugTarget,
    EvalResult,
    StackFrame,
    StopEvent,
    VariableValue,
)
from core.debug import (
    parse_breakpoint_specs,
    run_breakpoint_set,
    run_continue,
    run_evaluate,
    run_stack,
    run_targets,
    run_variables,
    run_wait,
)
from core.debug.state import (
    write_session,
)
from tests.helpers_debug import (
    SPIKE_OBJECT,
    SPIKE_TARGET,
    fake_session,
    init_project,
    persist_stop,
)

pytestmark = pytest.mark.usefixtures("stub_background_ping")


def test_breakpoint_set_and_wait_stack_vars_eval(tmp_path: Path) -> None:
    target = init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-1")

    stop = StopEvent(
        target_id=SPIKE_TARGET,
        frames=(
            StackFrame(
                object_id=SPIKE_OBJECT,
                property_id=PROPERTY_ID_COMMON_MODULE,
                line_no=42,
                module_name="ОтладкаДемо",
            ),
        ),
    )
    eval_result = EvalResult(
        state="correctly",
        variables=(
            VariableValue(name="Значение", type_name="Строка", presentation="x", value_raw="x"),
        ),
    )

    fake_targets = [DebugTarget(target_id=SPIKE_TARGET, target_type="Client", state="Attached")]

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        session = fake_session(
            set_breakpoints_by_module=MagicMock(
                return_value=BreakpointSpec(
                    object_id=SPIKE_OBJECT,
                    property_id=PROPERTY_ID_COMMON_MODULE,
                    lines=(42,),
                )
            ),
            stack=MagicMock(return_value=list(stop.frames)),
            variables=MagicMock(return_value=eval_result),
            evaluate=MagicMock(return_value=eval_result),
            continue_=MagicMock(side_effect=lambda *a, **k: persist_stop(target, stop) or "ok"),
            clear_cached_stop=MagicMock(),
            targets=MagicMock(return_value=fake_targets),
            ensure_targets_attached=MagicMock(return_value=fake_targets),
            stop_ping=MagicMock(),
            start_ping=MagicMock(),
            last_stop=stop,
            _last_stop=stop,
        )
        # resolver used only if real set_breakpoints_by_module — mocked
        session.resolver = SimpleNamespace()
        return session

    bp = run_breakpoint_set(
        target,
        module="ОтладкаДемо",
        module_type="CommonModule",
        lines=[42],
        session_factory=factory,
    )
    assert bp.status == "ok"
    assert bp.breakpoints[0]["lines"] == [42]

    # --file and --module are mutually exclusive
    both = run_breakpoint_set(
        target,
        module="ОтладкаДемо",
        file="Catalogs/Товары/Ext/ObjectModule.bsl",
        lines=[4],
        session_factory=factory,
    )
    assert both.status == "failed"
    assert both.exit_code == 2

    persist_stop(target, stop)
    waited = run_wait(target, timeout=1.0, session_factory=factory)
    assert waited.status == "ok"
    assert waited.line_no == 42
    assert waited.target_id == SPIKE_TARGET

    stack = run_stack(target, session_factory=factory)
    assert stack.status == "ok"
    assert len(stack.call_stack) == 1

    variables = run_variables(target, session_factory=factory)
    assert variables.status == "ok"
    assert variables.variables[0]["name"] == "Значение"

    ev = run_evaluate(target, expression="1+1", session_factory=factory)
    assert ev.status == "ok"
    assert ev.expression == "1+1"

    cont = run_continue(target, session_factory=factory)
    assert cont.status == "ok"
    assert cont.line_no == 42
    assert cont.call_stack

    targets = run_targets(target, session_factory=factory)
    assert targets.status == "ok"
    assert targets.targets[0]["targetId"] == SPIKE_TARGET


def test_parse_breakpoint_specs_merge_and_errors() -> None:
    specs, diags = parse_breakpoint_specs(
        [
            "src/main/Ext/ManagedApplicationModule.bsl:9",
            "src/main/Ext/ManagedApplicationModule.bsl:8",
            "Module.bsl:1,2",
            "bad-no-line",
        ]
    )
    assert len(diags) == 1
    by_file = {s.file: s.lines for s in specs}
    assert by_file["src/main/Ext/ManagedApplicationModule.bsl"] == (9, 8)
    assert by_file["Module.bsl"] == (1, 2)
