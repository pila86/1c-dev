# ADR-024: Platform templates (tmplts)

**Статус:** Accepted  
**Дата:** 2026-09-29

## Контекст

Сейчас onboarding конфигурации — `configuration.import --from *.cf` ([ADR-028](028-configuration-import.md)). На машине разработчика уже часто установлены шаблоны конфигураций платформы (каталог tmplts + манифесты `*.mft`). Нужен discovery и import без ручного поиска `.cf`.

## Решение

1. Probe в `adapters/platform/` (рядом с ADR-005):
   - читать `ConfigurationTemplatesLocation` из `1cestart.cfg` (Linux: `~/.1C/1cestart/`; Windows: APPDATA / All Users);
   - плюс default tmplts: Linux/macOS `~/.1cv8/1C/1cv8/tmplts`, Windows `%APPDATA%\1C\1cv8\tmplts`.
2. Рекурсивно находить `*.mft`, парсить INI-подобный формат (Vendor, Name, Version, секции Source/Catalog/…).
3. Публичный API:
   - `templates.roots` / `templates.list` / `templates.get`;
   - `configuration.import --from-template <id>`: resolve путь к `.cf` → reuse pipeline ADR-014/028;
   - для Source `.dt`: seed выбранного runtime (create/load), **не** подмена XML source без явного флага.
4. Doctor capability `templates` (gap ≠ hard-fail всего CLI).
5. MCP-зеркала `templates.*` + `from_template` у `configuration.import`.

Это **не** путать с git-шаблонами `templates/configuration/` в monorepo toolchain.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Discovery tmplts + reuse import `.cf` | Дёшево на базе M3 | Парсер mft / OS paths | **Принято** |
| Только ручной путь к `.cf` | Уже есть | Плохой DX | Недостаточно |
| Вызов GUI стартера 1С | «Как у пользователя» | Не agent-friendly | Отвергнуто |

## Последствия

- Новые пакеты `core/templates/` (оркестрация) + probe в platform discovery.
- ID шаблона в API стабилен в рамках сессии list (vendor/name/version/section или hash пути).

## Связанные решения

- ADR-005, ADR-014, ADR-015, ADR-022, ADR-028
- [M4](../milestones/m4-project-model.md)
