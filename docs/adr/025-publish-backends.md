# ADR-025: Publish backends (ibsrv / webinst)

**Статус:** Proposed  
**Дата:** 2026-09-29

## Контекст

Нужна публикация ИБ для веб-клиента / HTTP-сервисов в dev-контуре. Классический путь — Apache/`webinst` (часто нужны права root). Автономный сервер (`ibsrv`) обслуживает одну ИБ по HTTP без внешнего веб-сервера и удобнее для локального AI/dev.

## Решение

1. Продуктовый фасад: CLI/MCP `publish.up` / `publish.down` / `publish.status` / `publish.url` (точные имена при реализации можно слегка уточнить, сохранив группу `publish.*`).
2. Секция манифеста `publish` (schema `"2"`): `default` profile id + `profiles` map.
3. Профиль ссылается на элемент **`runtimes[]`** через `runtime: <id>` (ADR-026).
4. **Must backend:** `ibsrv` — YAML под `.1c-dev/publish/`, управление через `ibcmd server config` / запуск `ibsrv` (точные argv — spike).
5. **Should backend:** `webinst` (`-apache24` и др.) — doctor capability; отсутствие Apache/прав → gap, не hard-fail всего CLI.
6. Тонкие adapters: `adapters/ibsrv/`, `adapters/webinst/` — только subprocess + diagnostics; оркестрация в `core/publish/`.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| ibsrv first, webinst second | Dev без sudo; привычный Apache later | Два адаптера | **Принято (Proposed)** |
| Только Apache/webinst | Один путь | Хрупкий local DX | Отвергнуто как MVP |
| Только ручной default.vrd | Просто | Нет lifecycle API | Отвергнуто |

## Последствия

- Doctor: capabilities `ibsrv`, `webinst`.
- Не смешивать с metadata HTTPService (это объекты конфигурации, не публикация ИБ).

## Связанные решения

- ADR-005, ADR-019, ADR-022, ADR-026
- [M4](../milestones/m4-project-model.md)
