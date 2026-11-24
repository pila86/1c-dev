# ADR-034: Smart init adopt + external test paths

**Статус:** Accepted  
**Дата:** 2026-11-23

## Контекст

ADR-027 зафиксировал `project.init` как empty scope (`configurations: []`). Для brownfield
(уже есть XML/EDT в репозитории, часто на 1–2 уровня вложенности) агент/человек вынуждены
вручную вызывать `configuration.add` / править манифест — плохой DX и медленное внедрение.

Нужен adopt-pass после empty scaffold: обнаружить исходники и заполнить манифест.
Отдельно — возможность привязать YaXUnit test-extension из папки **вне** scope
(соседний репозиторий), не копируя исходники внутрь.

## Решение

### 1. Smart init (default)

Для `--type configuration`:

1. Как сейчас: empty scaffold (`.1c-dev/project.yaml`, AGENTS, IDE MCP).
2. Скан scope root на глубину **0–3** (`core/project/discover_sources.py`;
   depth 3 нужен для типичного `src/cfe/<ext>`).
3. Если найдены configuration-корни — зарегистрировать conf + extensions + runtime
   (`core/project/adopt.py`), без scaffold XML.
4. Если ничего не найдено — empty scope (регрессия ADR-027).
5. Только orphan extensions без conf → warning, манифест остаётся empty.

`--type extension` без adopt (standalone scaffold).

Конфликт с `--config`: при успешном adopt — не вызывать `configuration.add`, warning.

### 2. Маркеры и классификация

| Формат | Корень | Conf vs extension |
|--------|--------|-------------------|
| XML | `Configuration.xml` | extension: `ObjectBelonging=Adopted` / `ConfigurationExtensionPurpose` / непустой `NamePrefix` |
| EDT | `.project`+V8 nature и/или `src/Configuration/Configuration.mdo` | extension-признаки в `.mdo` / соседство; иначе conf + warning |

Пропуск: `.git`, `.1c-dev`, `build`, `.runtime`, `.cache`, `node_modules`, `.venv`, `__pycache__`, скрытые `.`*.

### 3. YaXUnit heuristics

`purpose: tests`, если модули с `ИсполняемыеСценарии` **или** имя/id содержит
`test` / `tests` / `yaxunit` / `юнит`. При наличии → suite `id: unit`, `runner: yaxunit`.
Runner `.cfe` по-прежнему cache / ensure (ADR-029), не в манифест.

### 4. External test paths (post-init)

- Скан init **не** выходит за scope.
- Для `extensions[].purpose: tests` допускается `source.path` вида `../…` или absolute.
- Product conf/extensions — только in-tree relative (без `..` / absolute).
- CLI: `extension add --path <dir> --purpose tests` — register existing layout без scaffold;
  mutually exclusive с `--from`; при `purpose: tests` wire suite `unit`.
- В манифест предпочитать portable relative вне scope.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Умный init по умолчанию | Лучший DX brownfield | Меняет ожидание «init = empty» | **Принято** (empty + adopt-pass) |
| Флаг `--detect` / команда `adopt` | Явный контракт | Лишний шаг онбординга | Отвергнуто |
| Автоскан вне scope | Ещё меньше ручной работы | Непредсказуемо | Отвергнуто |

## Последствия

- ADR-027 дополнен: empty bootstrap сохраняется; adopt — второй шаг того же `init`.
- ADR-029 дополнен: external `source.path` для `purpose: tests`.
- MCP `project.init` наследует поведение без смены API; `extension.add` получает `path`.

## Связанные решения

- ADR-027, ADR-029, ADR-032
- [M4](../archive/milestones/m4-project-model.md), [M5](../archive/milestones/m5-tests.md)
