# Как устроен 1c-dev

Обзор для пользователя продукта: слои, границы и термины.  
Что нужно поставить и что подтягивается само — в [dependencies.md](dependencies.md).  
Почему так решили — в [ADR](../adr/README.md).

## Идея

`1c-dev` — **оркестратор** над платформой 1С и вспомогательными инструментами, а не их замена. Он не подменяет Конфигуратор, EDT, платформу или тестовый фреймворк: управляет ими через единый CLI и MCP для человека и AI-агента.

Принципы:

- не привязан к конкретному агенту или IDE;
- не привязан к формату исходников (XML Конфигуратора или EDT);
- наружу — JSON и структурированные диагностики, внутрь — `ibcmd`, jar, HTTP debug и т.п.

## Слои

```text
Человек ── CLI (`1c-dev …`) ──┐
Агент  ── MCP (`1c-dev mcp`) ─┼──► core (оркестрация, манифест, IR)
                              │
                              ├── adapters ──► ibcmd / 1cv8 / dbgs / 1cedtcli
                              ├── toolchain ──► jar в user cache (xml-gen, md-reader, …)
                              └── catalog/services ──► внешние MCP (v8std, bsl-ls, …)
```

| Слой | Роль |
|------|------|
| CLI / MCP | Один и тот же продукт: команды человека и tools агента |
| core | Манифест проекта, сценарии (build, test, debug), семантика метаданных (IR) |
| adapters | Вызов платформы и внешних бинарей |
| toolchain | Внутренние зависимости продукта в cache |
| catalog / services | Опциональные внешние инструменты; install ≠ run |

## Scope проекта

Рабочая единица — **scope**: каталог с `.1c-dev/project.yaml` (schema `"2"`).

| Путь | Что это |
|------|---------|
| `.1c-dev/project.yaml` | Конфигурации, расширения, runtimes, publish |
| `.1c-dev/runtime/` | Файловые ИБ и служебное состояние runtime |
| `.1c-dev/tools.yaml` | Desire-list внешних tools (опционально, не создаётся `init`) |
| исходники XML или EDT | Код конфигурации / расширения (владеет пользователь) |
| `.cursor/` / `.kilo/`, `AGENTS.md` | Подключение IDE и подсказки агенту — не исходники 1С |

Несколько конфигураций и расширений живут в одном scope. В monorepo MCP можно писать в корень workspace (`ide configure --ide-root`), а scope держать nested.

## Две разные подсистемы «tools»

Имена похожи — смысл разный. Подробности зависимостей: [dependencies.md](dependencies.md).

| | **Toolchain** | **External tools** |
|--|---------------|-------------------|
| Зачем | Внутренние jar/soft-deps самого `1c-dev` | Сторонние MCP и сервисы из `catalog/` |
| CLI | `toolchain sync` / `clean` | `tools install` / `remove` / `check`; `services up` / `down` / … |
| Alias | `tools sync` → `toolchain sync` (переходный) | — |
| Где | `~/.cache/1c-dev/tools/` | `~/.local/share/1c-dev/tools/<id>/` |
| `clean` | Чистит cache | Не трогает share; сервисы — отдельно `services down` |

Установка внешнего tool **не** запускает сервис. После `services up` для IDE обычно нужен повторный `ide configure`.

## Метаданные: IR, не сырой XML

Агент и CLI работают с **IR** (промежуточная модель объекта: имя, синоним, реквизиты, типы…).  
Запись в XML идёт через xml-gen; чтение — через md-reader (MDClasses); для EDT write — md-sparrow. Платформенная сборка и проверка — через `ibcmd` (и при EDT — `1cedtcli` export).

Ссылочные типы в create/update: `type=Ref` + `reference=Catalog.X`, не литералы вроде `CatalogRef.X`.

## Куда читать дальше

| Нужно | Документ |
|-------|----------|
| Явные и неявные зависимости | [dependencies.md](dependencies.md) |
| Сценарии | [../user-guide.md](../user-guide.md) |
| Команды | [../cli-reference.md](../cli-reference.md) |
| MCP tools | [../mcp.md](../mcp.md) |
| Углубление по темам | [../adr/README.md](../adr/README.md) |
