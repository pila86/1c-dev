# ADR-030: Designer `/CheckModules` в `1c-dev check`

**Статус:** Accepted  
**Дата:** 2026-10-08

## Контекст

`1c-dev check` (ADR-009) вызывает только `ibcmd infobase config check`. На платформе 8.3.25 это **проверка корректности метаданных**, а не синтаксический контроль модулей: заведомо сломанный BSL (`А = ;`, нет `КонецПроцедуры`) проходит ibcmd с rc=0, тогда как `1cv8 DESIGNER /CheckModules -Server` возвращает ошибки с модулем/строкой/колонкой.

PRD §24 разделяет `check.static` (BSL LS) и `check.platform`. Статический анализ не заменяет компилятор платформы. Batch Designer допустим в product API; интерактивный Конфигуратор по-прежнему вне scope (агент не вызывает Designer вручную).

## Решение

### Pipeline

```text
ibcmd infobase config check          # A: metadata
1cv8 DESIGNER … /CheckModules …      # B: module syntax
```

Оба шага обязательны. Diagnostics накапливаются (не fail-fast после A). Успех = оба шага без ошибок.

### Adapter

`adapters/platform_1cv8/` — subprocess:

```text
1cv8 DESIGNER /F<ib> /DisableStartupDialogs /DisableStartupMessages
  /Out <log> /CheckModules -Server [-ThinClient …]
```

Парсинг `/Out` → structured diagnostics (`object`, `module`, `line`, `column`, `source: "platform"`). Паттерн запуска/timeout — как у YaXUnit (ADR-029), без xvfb для DESIGNER batch.

### Режимы

Default: `-Server`. Override через CLI/MCP `--mode` (repeatable).

### Diagnostics и exit codes

| Ситуация | Code | Exit |
|----------|------|------|
| Нет `ibcmd` | `1CC001` | `ENV_UNAVAILABLE` (3) |
| Нет `1cv8` | `1CC005` | `ENV_UNAVAILABLE` (3) |
| Нет/битый проект | `1CC002` | `PROJECT_ERROR` (2) |
| Нет file IB | `1CC003` | `PROJECT_ERROR` (2) |
| Ошибки metadata и/или modules | `1CC004` | `CHECK_FAILURE` (1) |

Doctor capability `check` требует `ibcmd` **и** `1cv8`.

### Граница

- `/CheckConfig` — later.
- Soft-degrade без `1cv8` — отвергнуто (агент иначе пропускает синтаксис).
- Modes / filter в `project.yaml`, `/Extension` — later.
- `check.static` (BSL LS) — отдельный трек PRD, не часть этого ADR.
- Auto-build перед check — по-прежнему отвергнуто (ADR-009).

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Только ibcmd (status quo) | Проще | Не ловит синтаксис модулей | Отвергнуто |
| Только `/CheckModules` | Узко | Теряем metadata gate ibcmd | Отвергнуто |
| `/CheckConfig` сразу | Шире проверки | Тяжелее, шумнее; scope | Отложено |
| Modules по флагу / soft без 1cv8 | Совместимость | Агент пропускает шаг | Отвергнуто |
| A + `/CheckModules` (default Server) | Закрывает дыру; предсказуемо | Нужен 1cv8; lock IB | **Принято** |

## Последствия

- CLI/MCP `check` меняет контракт: нужен `1cv8`; payload может включать `steps: ["metadata","modules"]`.
- AGENTS / README: check = metadata + платформенный синтаксис модулей.
- Integration-тесты check требуют и ibcmd, и 1cv8.

## Связанные решения

- ADR-003, ADR-005, ADR-009 (дополняется), ADR-029
- PRD §24, §35–§36, §52
