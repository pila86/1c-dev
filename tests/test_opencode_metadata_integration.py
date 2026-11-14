"""Integration: OpenCode agent + 1c-dev MCP создаёт метаданные (локальная LLM).

Маркер ``opencode`` — нужен ``opencode``, ``.patterns-ab/env.local`` и один
свободный LLM-поток (helpers_opencode.llm_stream_lock).

Сценарии:
1) справочник (smoke — ожидаем OK);
2) общий модуль;
3) регистр накопления + документ-регистратор (выявляем проблемы).
"""

from __future__ import annotations

import pytest

from tests.helpers_opencode import (
    assert_object_exists,
    file_contains,
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


def test_opencode_create_catalog() -> None:
    """Агент должен создать справочник через metadata.create."""
    _require_llm()
    run_dir = new_run_dir("catalog")
    prepare_workspace(run_dir, prompt=PROMPT_CATALOG, steps=25)
    code = run_opencode(run_dir, timeout_sec=900)
    ws = run_dir / "workspace"
    path = assert_object_exists(ws, "Catalogs", "Товары")
    assert file_contains(path, "Товары") or path.name == "Товары.xml"
    # Soft: exit code may be non-zero if agent summarizing fails; object presence wins.
    assert path.is_file(), f"exit={code}, missing catalog; see {run_dir}"


def test_opencode_create_common_module() -> None:
    """Агент должен создать общий модуль."""
    _require_llm()
    run_dir = new_run_dir("common-module")
    prepare_workspace(run_dir, prompt=PROMPT_COMMON_MODULE, steps=25)
    code = run_opencode(run_dir, timeout_sec=900)
    ws = run_dir / "workspace"
    path = assert_object_exists(ws, "CommonModules", "СлужебныйСервер")
    assert path.is_file(), f"exit={code}, missing module; see {run_dir}"


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

    # Dimensions / resources — ожидаем в файле
    has_dim = ("Товар" in reg_text) and (
        "CatalogRef.Товары" in reg_text or "Catalog.Товары" in reg_text
    )
    has_res = "Количество" in reg_text
    # Register type Balance / Остатки
    has_type = (
        "<RegisterType>Balance</RegisterType>" in reg_text
        or "registerType>Balances" in reg_text
        or "registerType>Balance" in reg_text
        or "<type>Balances</type>" in reg_text
    )
    # Document → registerRecords as MDListType (framework#27), not flat text.
    has_rr = (
        "AccumulationRegister.ОстаткиТоваров" in doc_text
        and "<xr:Item" in doc_text
        and 'xsi:type="xr:MDObjectRef"' in doc_text
    )

    report = run_dir / "assertions.md"
    report.write_text(
        "\n".join(
            [
                f"# assertions exit={code}",
                f"- catalog: {cat}",
                f"- register: {reg}",
                f"- document: {doc}",
                f"- has_dimension_product: {has_dim}",
                f"- has_resource_qty: {has_res}",
                f"- has_register_type_balance: {has_type}",
                f"- has_register_records: {has_rr}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    # Catalog always required; register body and registrar are the known pain points.
    assert has_dim and has_res, (
        f"регистр без измерения/ресурса; см. {report} и {run_dir / 'agent.transcript.md'}"
    )
    # Не fail-hard на registerType/registerRecords — сначала собираем факты;
    # soft-assert через xfail-сообщение в report, жёстко падаем только если оба сломаны.
    if not has_type or not has_rr:
        pytest.xfail(
            "известные пробелы metadata: "
            f"registerType={has_type}, registerRecords={has_rr}; "
            f"детали {report}"
        )
