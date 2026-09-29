# ADR-026: Runtimes array (ИБ ↔ configuration)

**Статус:** Accepted  
**Дата:** 2026-09-29

## Контекст

В schema `"1"` один блок `runtime: { type, path }`. При нескольких конфигурациях нужна как минимум одна ИБ на каждую; также допустимы несколько ИБ на одну configuration (dev/demo). Связь должна быть явной в манифесте.

## Решение

1. Top-level **`runtimes`** — **массив** (не map), элементы:

   | Поле | Обязательно | Смысл |
   |------|-------------|--------|
   | `id` | да | Стабильный id для CLI/MCP `--runtime` |
   | `configuration` | да | `id` из `configurations[]` |
   | `type` | да | Пока `file` (server — later) |
   | `path` | да | Путь к ИБ relative к scope root |
   | `default` | нет | `true` — не более одного на весь манифест |

2. **Инварианты validate:**
   - у каждой `configurations[].id` есть ≥1 элемент в `runtimes` с этим `configuration`;
   - ровно один элемент с `default: true` (global default для операций без `--runtime`);
   - `configuration` ссылается на существующий id.

3. У `configurations[]` **нет** поля `runtime:` — связь только из `runtimes[]`.

4. `build` / `runtime.*` / `publish` / clean резолвят ИБ через `runtimes[]`; `--config` уточняет, если у configuration несколько ИБ и runtime не указан (если одна ИБ — можно выбрать её автоматически).

5. Init создаёт одну configuration + один связанный runtime (`path`: `.1c-dev/runtime/<config-id>`, `default: true`).

6. Publish-профиль указывает `runtime: <id>` (ADR-025).

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| `runtimes[]` со связью на configuration | Явно; N ИБ на config | Чуть длиннее yaml | **Принято** |
| `runtime:` у каждой configuration | Короче | Несколько ИБ на config неудобны | Отвергнуто |
| Map `runtimes: { id: {…} }` без configuration | Привычный map | Связь с config неочевидна | Отвергнуто |

## Последствия

- Миграция schema `"1"`: один элемент `runtimes[]` из бывшего `runtime`.
- Client state / pid (ADR-019) — per-runtime path под home.

## Связанные решения

- ADR-004, ADR-019, ADR-021, ADR-022, ADR-023, ADR-025
- [M4](../milestones/m4-project-model.md)
- Schema: [`schemas/1c.project.schema.v2.json`](../../schemas/1c.project.schema.v2.json)
