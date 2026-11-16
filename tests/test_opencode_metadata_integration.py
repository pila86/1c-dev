"""Integration: OpenCode agent + 1c-dev MCP создаёт метаданные (локальная LLM).

Маркер ``opencode`` — нужен ``opencode``, креды ``LLM_*`` (process env или
``tests/.env.integration``) и один свободный LLM-поток
(helpers_opencode.llm_stream_lock).

Сценарии (по возрастанию сложности):
- Catalog, CommonModule, Enum, Constant, Document, InformationRegister,
  Subsystem(+content), AccumulationRegister+регистратор.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers_opencode import (
    assert_object_exists,
    llm_ready,
    new_run_dir,
    prepare_workspace,
    run_opencode,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.opencode,
]


def _require_llm() -> None:
    ok, reason = llm_ready()
    if not ok:
        pytest.skip(reason)


def _run_stats(run_dir: Path) -> dict[str, int | str]:
    """Collect step/tool counts from agent.jsonl for assertions.md."""
    jsonl = run_dir / "agent.jsonl"
    steps = tools = 0
    tool_names: list[str] = []
    if jsonl.is_file():
        for line in jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            part = ev.get("part") or {}
            t = ev.get("type")
            if t == "step_start" or part.get("type") == "step-start":
                steps += 1
            if t == "tool_use" or part.get("type") == "tool":
                tools += 1
                tool_names.append(str(part.get("tool") or "?"))
    return {
        "steps": steps,
        "tools": tools,
        "tool_chain": " -> ".join(tool_names),
    }


def _write_report(run_dir: Path, code: int, lines: list[str]) -> Path:
    stats = _run_stats(run_dir)
    report = run_dir / "assertions.md"
    body = [
        f"# assertions exit={code}",
        f"- steps: {stats['steps']}",
        f"- tools: {stats['tools']}",
        f"- tool_chain: {stats['tool_chain']}",
        *lines,
        "",
    ]
    report.write_text("\n".join(body), encoding="utf-8")
    return report


# --- prompts -----------------------------------------------------------------

PROMPT_CATALOG = """\
Ты работаешь в этом workspace через MCP-инструменты 1c-dev.

Задача:
1. Создай справочник Catalog.Товары (синоним «Товары») с реквизитом Артикул:String:50.
2. Проверь через metadata.get / metadata.list, что объект существует.
3. Кратко перечисли созданные объекты.

Используй только MCP 1c-dev (metadata.create и т.п.). Не выдумывай CLI платформы.
"""

PROMPT_COMMON_MODULE = """\
Ты работаешь в этом workspace через MCP-инструменты 1c-dev.

Задача:
1. Создай общий модуль CommonModule.СлужебныйСервер с флагами server=true, server_call=true.
2. Проверь через metadata.get, что модуль существует.
3. Кратко перечисли созданные объекты.

Используй только MCP 1c-dev. Не пиши тело BSL, если инструмент этого не делает.
"""

PROMPT_ENUM = """\
Ты работаешь в этом workspace через MCP-инструменты 1c-dev.

Задача:
1. Создай перечисление Enum.СтатусыЗаказа (синоним «Статусы заказа»)
   со значениями New/Новый и Done/Выполнен.
2. Проверь metadata.get.
3. Кратко перечисли созданные объекты.

Только MCP 1c-dev.
"""

PROMPT_CONSTANT = """\
Ты работаешь в этом workspace через MCP-инструменты 1c-dev.

Задача:
1. Создай константу Constant.СтавкаНДС (синоним «Ставка НДС») типа Number 5.2
   (или value_type Number с precision/scale).
2. Проверь metadata.get.
3. Кратко перечисли созданные объекты.

Только MCP 1c-dev.
"""

PROMPT_DOCUMENT = """\
Ты работаешь в этом workspace через MCP-инструменты 1c-dev.

Задача:
1. Создай справочник Catalog.Контрагенты (без лишних реквизитов).
2. Создай документ Document.Заказ (синоним «Заказ») с:
   - реквизитом Контрагент → Catalog.Контрагенты;
   - табличной частью Товары: Номенклатура:String:100, Количество:Number:15.2.
3. Проверь metadata.get по документу.
4. Кратко перечисли созданные объекты.

Только MCP 1c-dev. Без регистров и проведения.
"""

PROMPT_INFO_REGISTER = """\
Ты работаешь в этом workspace через MCP-инструменты 1c-dev.

Задача:
1. Создай справочник Catalog.Товары.
2. Создай регистр сведений InformationRegister.ЦеныТоваров (синоним «Цены товаров»):
   - измерение Товар → Catalog.Товары;
   - ресурс Цена → Number 15.2.
3. Проверь metadata.get по регистру.
4. Кратко перечисли созданные объекты.

Только MCP 1c-dev. Без документов.
"""

PROMPT_SUBSYSTEM = """\
Ты работаешь в этом workspace через MCP-инструменты 1c-dev.

Задача:
1. Создай справочник Catalog.Товары.
2. Создай подсистему Subsystem.Склад (синоним «Склад») и включи в её состав
   Catalog.Товары (content / add-content).
3. Проверь metadata.get по подсистеме.
4. Кратко: созданные объекты и удалось ли записать состав.

Только MCP 1c-dev.
"""

PROMPT_REGISTER = """\
Ты работаешь в этом workspace через MCP-инструменты 1c-dev.

Задача — минимальная учётная схема остатков:
1. Справочник Catalog.Товары (синоним «Товары»).
2. Регистр накопления AccumulationRegister.ОстаткиТоваров, вид Остатки (Balance):
   - измерение Товар → Catalog.Товары;
   - ресурс Количество → Number 15.2.
3. Документ Document.ОприходованиеТоваров с табличной частью Товары (Товар, Количество)
   и зарегистрируй его как регистратор движений по AccumulationRegister.ОстаткиТоваров
   (свойство registerRecords / RegisterRecords документа).

После создания проверь metadata.get по регистру и документу.
В конце кратко: какие объекты созданы и удалось ли выставить registerRecords.

Используй только MCP 1c-dev. Не реализуй проведение и не делай build,
если не нужно для проверки метаданных.
"""


# --- tests -------------------------------------------------------------------


def test_opencode_create_catalog() -> None:
    """Агент должен создать справочник через metadata.create."""
    _require_llm()
    run_dir = new_run_dir("catalog")
    prepare_workspace(run_dir, prompt=PROMPT_CATALOG, steps=25)
    code = run_opencode(run_dir, timeout_sec=900)
    ws = run_dir / "workspace"
    path = assert_object_exists(ws, "Catalogs", "Товары")
    _write_report(run_dir, code, [f"- catalog: {path}"])
    assert path.is_file(), f"exit={code}, missing catalog; see {run_dir}"


def test_opencode_create_common_module() -> None:
    """Агент должен создать общий модуль."""
    _require_llm()
    run_dir = new_run_dir("common-module")
    prepare_workspace(run_dir, prompt=PROMPT_COMMON_MODULE, steps=25)
    code = run_opencode(run_dir, timeout_sec=900)
    ws = run_dir / "workspace"
    path = assert_object_exists(ws, "CommonModules", "СлужебныйСервер")
    _write_report(run_dir, code, [f"- module: {path}"])
    assert path.is_file(), f"exit={code}, missing module; see {run_dir}"


def test_opencode_create_enum() -> None:
    """Агент должен создать перечисление со значениями."""
    _require_llm()
    run_dir = new_run_dir("enum")
    prepare_workspace(run_dir, prompt=PROMPT_ENUM, steps=25)
    code = run_opencode(run_dir, timeout_sec=900)
    ws = run_dir / "workspace"
    path = assert_object_exists(ws, "Enums", "СтатусыЗаказа")
    text = path.read_text(encoding="utf-8-sig")
    has_new = "New" in text or "Новый" in text
    has_done = "Done" in text or "Выполнен" in text
    _write_report(
        run_dir,
        code,
        [f"- enum: {path}", f"- has_new: {has_new}", f"- has_done: {has_done}"],
    )
    assert has_new and has_done, f"нет значений enum; см. {run_dir}"


def test_opencode_create_constant() -> None:
    """Агент должен создать константу с числовым типом."""
    _require_llm()
    run_dir = new_run_dir("constant")
    prepare_workspace(run_dir, prompt=PROMPT_CONSTANT, steps=25)
    code = run_opencode(run_dir, timeout_sec=900)
    ws = run_dir / "workspace"
    path = assert_object_exists(ws, "Constants", "СтавкаНДС")
    text = path.read_text(encoding="utf-8-sig")
    has_number = "Number" in text or "xs:decimal" in text or "decimal" in text.lower()
    _write_report(
        run_dir,
        code,
        [f"- constant: {path}", f"- has_number_type: {has_number}"],
    )
    assert path.is_file() and has_number, f"константа без Number; см. {run_dir}"


def test_opencode_create_document_with_tabular() -> None:
    """Агент: документ с реквизитом-ссылкой и табличной частью."""
    _require_llm()
    run_dir = new_run_dir("document")
    prepare_workspace(run_dir, prompt=PROMPT_DOCUMENT, steps=40)
    code = run_opencode(run_dir, timeout_sec=1200)
    ws = run_dir / "workspace"
    cat = assert_object_exists(ws, "Catalogs", "Контрагенты")
    doc = assert_object_exists(ws, "Documents", "Заказ")
    text = doc.read_text(encoding="utf-8-sig")
    has_ref = "Контрагент" in text or "CatalogRef.Контрагенты" in text
    has_ts = "Товары" in text and ("Количество" in text or "Qty" in text)
    _write_report(
        run_dir,
        code,
        [
            f"- catalog: {cat}",
            f"- document: {doc}",
            f"- has_counterparty_ref: {has_ref}",
            f"- has_tabular_goods: {has_ts}",
        ],
    )
    assert has_ref and has_ts, f"документ без реквизита/ТЧ; см. {run_dir}"


def test_opencode_create_information_register() -> None:
    """Агент: регистр сведений с измерением и ресурсом."""
    _require_llm()
    run_dir = new_run_dir("info-register")
    prepare_workspace(run_dir, prompt=PROMPT_INFO_REGISTER, steps=40)
    code = run_opencode(run_dir, timeout_sec=1200)
    ws = run_dir / "workspace"
    cat = assert_object_exists(ws, "Catalogs", "Товары")
    reg = assert_object_exists(ws, "InformationRegisters", "ЦеныТоваров")
    text = reg.read_text(encoding="utf-8-sig")
    has_dim = "Товар" in text and (
        "CatalogRef.Товары" in text or "Catalog.Товары" in text
    )
    has_res = "Цена" in text or "Price" in text
    _write_report(
        run_dir,
        code,
        [
            f"- catalog: {cat}",
            f"- register: {reg}",
            f"- has_dimension: {has_dim}",
            f"- has_resource: {has_res}",
        ],
    )
    assert has_dim and has_res, f"РС без измерения/ресурса; см. {run_dir}"


def test_opencode_create_subsystem_with_content() -> None:
    """Агент: подсистема и состав (content); на XML ожидаем успех."""
    _require_llm()
    run_dir = new_run_dir("subsystem")
    prepare_workspace(run_dir, prompt=PROMPT_SUBSYSTEM, steps=40)
    code = run_opencode(run_dir, timeout_sec=1200)
    ws = run_dir / "workspace"
    cat = assert_object_exists(ws, "Catalogs", "Товары")
    sub = assert_object_exists(ws, "Subsystems", "Склад")
    text = sub.read_text(encoding="utf-8-sig")
    # XML: <Content>…Catalog.Товары… or xr:Item; EDT may lack content (gap).
    has_content = "Catalog.Товары" in text or "Товары" in text
    _write_report(
        run_dir,
        code,
        [
            f"- catalog: {cat}",
            f"- subsystem: {sub}",
            f"- has_content_ref: {has_content}",
        ],
    )
    assert sub.is_file(), f"подсистема не создана; см. {run_dir}"
    if not has_content:
        pytest.xfail(f"состав подсистемы не записан; см. {run_dir}")


def test_opencode_create_accumulation_register_and_registrar() -> None:
    """Агент: регистр накопления + регистратор; фиксируем фактический результат."""
    _require_llm()
    run_dir = new_run_dir("accum-register")
    prepare_workspace(run_dir, prompt=PROMPT_REGISTER, steps=60)
    code = run_opencode(run_dir, timeout_sec=1800)
    ws = run_dir / "workspace"

    cat = assert_object_exists(ws, "Catalogs", "Товары")
    reg = assert_object_exists(ws, "AccumulationRegisters", "ОстаткиТоваров")
    doc = assert_object_exists(ws, "Documents", "ОприходованиеТоваров")

    reg_text = reg.read_text(encoding="utf-8")
    doc_text = doc.read_text(encoding="utf-8")

    has_dim = ("Товар" in reg_text) and (
        "CatalogRef.Товары" in reg_text or "Catalog.Товары" in reg_text
    )
    has_res = "Количество" in reg_text
    has_type = (
        "<RegisterType>Balance</RegisterType>" in reg_text
        or "registerType>Balances" in reg_text
        or "registerType>Balance" in reg_text
        or "<type>Balances</type>" in reg_text
    )
    has_rr = (
        "AccumulationRegister.ОстаткиТоваров" in doc_text
        and "<xr:Item" in doc_text
        and 'xsi:type="xr:MDObjectRef"' in doc_text
    )

    report = _write_report(
        run_dir,
        code,
        [
            f"- catalog: {cat}",
            f"- register: {reg}",
            f"- document: {doc}",
            f"- has_dimension_product: {has_dim}",
            f"- has_resource_qty: {has_res}",
            f"- has_register_type_balance: {has_type}",
            f"- has_register_records: {has_rr}",
        ],
    )

    assert has_dim and has_res, (
        f"регистр без измерения/ресурса; см. {report} и {run_dir / 'agent.transcript.md'}"
    )
    if not has_type or not has_rr:
        pytest.xfail(
            "известные пробелы metadata: "
            f"registerType={has_type}, registerRecords={has_rr}; "
            f"детали {report}"
        )
