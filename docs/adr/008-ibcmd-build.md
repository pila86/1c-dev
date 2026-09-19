# ADR-008: Platform adapter ibcmd build

**Статус:** Accepted  
**Дата:** 2026-09-19

## Контекст

Issue #7 и M1 требуют `1c-dev build`: загрузка XML-конфигурации в file-IB без Конфигуратора, со structured diagnostics и exit code 6. Discovery (`ibcmd`) уже есть (ADR-005); init создаёт `.runtime/ib` (ADR-006). Нужен контракт pipeline и критерий успеха (`.cf` vs успешный apply).

## Решение

### Пакет

`adapters/platform_ibcmd/` — subprocess к `ibcmd` (путь из `discover_environment()`).  
Оркестрация — `core/build/`; CLI — `1c-dev build`.

### Pipeline (M1)

```text
ibcmd infobase create --db-path=<runtime.path> --data=<root>/.runtime/ibcmd-data
ibcmd infobase config import --db-path=… --data=… <source.path>
ibcmd infobase config apply --db-path=… --data=… --force
```

`--data` — каталог данных автономного сервера в проекте (избегает глобальной блокировки `~/.1cv8/.../standalone-server`).

`create` выполняется только если в `runtime.path` нет файла `1Cv8.1CD`.

### Критерий успеха

Успех по умолчанию = create (при необходимости) + import + apply.  
Артефакт `.cf` не обязателен.

`1c-dev build --artifact cf` дополнительно:

```text
ibcmd config save --db-path=… --data=… --db <root>/build/out/configuration.cf
```

### Diagnostics и exit codes

| Ситуация | Code | Exit |
|----------|------|------|
| Нет `ibcmd` | `1CB001` | `ENV_UNAVAILABLE` (3) |
| Нет/битый проект | `1CB002` | `PROJECT_ERROR` (2) |
| `source.format` ≠ xml | `1CB003` | `PROJECT_ERROR` (2) |
| Нет каталога source | `1CB004` | `PROJECT_ERROR` (2) |
| Ошибка шага ibcmd | `1CB005` | `BUILD_FAILURE` (6) |
| Неизвестный `--artifact` | `1CB006` | `PROJECT_ERROR` (2) |

`source` в diagnostics для платформы: `"platform"`.

### Граница с #9

`config check` / `1c-dev check` — отдельный issue (#9), не часть build.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Успех = apply (без обязательного `.cf`) | Совпадает с M1 flow; быстрее | Нет `.cf` по умолчанию | **Принято** |
| Успех только при `.cf` | Явный артефакт | Лишний шаг; не нужен агенту M1 | Отвергнуто |
| Fallback на `1cv8` | Шире покрытие | Scope #7 | Отложено |
| Глобальный `--data` ibcmd | Меньше argv | Блокировки между проектами | Отвергнуто |

## Последствия

- MCP `build` (#6) переиспользует `core.build.run_build`.
- Doctor capability `build` уже требует `ibcmd`.
- Integration-тесты skip без платформы.

## Связанные решения

- ADR-003, ADR-005, ADR-006, ADR-007
- Issue #7
- PRD §22–§23, §35–§36, §52
