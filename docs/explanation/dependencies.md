# Зависимости: явное и неявное

Что нужно поставить самому, что качает `1c-dev`, и что происходит «под капотом» команд.  
Общая модель слоёв — [overview.md](overview.md).

## Hard / soft

| Класс | Поведение |
|-------|-----------|
| **Hard** | Без компонента команда не выполняется (`ENV_UNAVAILABLE` / явная ошибка) |
| **Soft** | `toolchain sync` / `doctor` живут без компонента; сценарий, которому он нужен, деградирует или пропускается |

Проверка окружения: `1c-dev doctor` (или `doctor --fix` ≈ sync + повтор).

## Явно ставит пользователь

| Компонент | Зачем | Класс |
|-----------|--------|-------|
| [uv](https://docs.astral.sh/uv/) + пакет `1c-dev` | CLI и MCP-сервер в PATH | hard для всего продукта |
| JDK **25+** ([Temurin](https://adoptium.net/) и др.) | Единый для сборки/запуска jar toolchain | hard для metadata/docs/EDT write; sync тоже ждёт 25+ |
| Платформа [1С](https://v8.1c.ru/) 8.3.x, `ibcmd` | build, check, import `.cf`, работа с ИБ | hard для platform-сценариев |
| `1cv8` (клиент) | `runtime start`, часть test/debug | hard для этих сценариев |
| `dbgs` | HTTP Debug Protocol (входит в платформу) | hard для debug |
| `1cedtcli` ([1C:EDT](https://edt.1c.ru/)) | EDT: convert, build/check path | hard для EDT-сценариев |
| [Docker](https://docs.docker.com/get-docker/) | Часть external tools (compose) | hard для соответствующих services |

Override путей: `JAVA_HOME`, `ONEC_EDTCLI`, `ONEC_*_JAR`, `ONEC_YAXUNIT_CFE`, `ONEC_APACHE_HOME`, `ONEC_BSLLS_JAR`.

## Явно делает продукт (по команде)

### Toolchain → user cache

```bash
1c-dev toolchain sync
```

Кладёт артефакты в `~/.cache/1c-dev/tools/` (Windows: `%LOCALAPPDATA%\1c-dev\tools\`).  
Манифест pin’ов: `toolchain/manifest.yaml` ([ADR-013](../adr/013-packaging-toolchain-cache.md)).

| Артефакт | Источник | Зачем | Класс |
|----------|----------|--------|-------|
| xml-gen | [SteelMorgan/…/xml-gen](https://github.com/SteelMorgan/1c-agent-based-dev-framework/tree/master/tools/xml-gen) | `metadata.create` / `update` / `delete` (XML) | hard для write XML |
| md-reader | обёртка над [MDClasses](https://github.com/1c-syntax/mdclasses) (`tools/md-reader`) | `metadata.list` / `get` / `find` | hard для read |
| docs-facade | обёртка над [bsl-context](https://github.com/1c-syntax/bsl-context) (`tools/docs-facade`) | `docs search` / `get` | hard для docs |
| md-sparrow | [yellow-hammer/md-sparrow](https://github.com/yellow-hammer/md-sparrow) | write при `source.format: edt` | soft |
| yaxunit `.cfe` | [bia-technologies/yaxunit](https://github.com/bia-technologies/yaxunit) | runner тестов | soft |
| apache (httpd home) | [Apache HTTP Server](https://httpd.apache.org/) (сборка/zip в sync) | `publish` backend webinst | soft |

`toolchain clean --yes` удаляет cache. **Не** удаляет external tools в share.

Alias на переходный период: `1c-dev tools sync` = `toolchain sync`.

### External tools → share + services

```bash
1c-dev tools install --all    # файлы/образы в share; сервис не стартует
1c-dev services up --all      # только уже installed managed
1c-dev ide configure          # MCP endpoints в IDE
```

Каталог recipes: `catalog/`. Share: `~/.local/share/1c-dev/tools/<id>/`. State: `~/.local/share/1c-dev/services/`.  
Подробнее: [ADR-033](../adr/033-external-tools-manager.md).

| Tool | Источник | Зачем |
|------|----------|--------|
| v8std | [zeegin/v8std](https://github.com/zeegin/v8std) | стандарты разработки 1С (MCP) |
| bsl-ls | [1c-syntax/bsl-language-server](https://github.com/1c-syntax/bsl-language-server) | BSL LS как shared MCP (не в `toolchain sync`) |
| bsl-search | [axel-avb/mcp-bsl-search](https://github.com/axel-avb/mcp-bsl-search) | поиск по корпусу BSL (ES + MCP) |

## Неявное поведение

То, чего нет в «очевидной» команде, но продукт делает сам:

| Когда | Что происходит неявно |
|-------|------------------------|
| `test run` / часть test MCP | `yaxunit ensure`: runner `.cfe` из cache подключается к ИБ (без ручного `extension add YAXUNIT`) |
| `docs search` / `get` | При необходимости строится/обновляется lazy-индекс синтакс-помощника в cache (`docs/`) |
| `build` / `check` при `format: edt` | `1cedtcli export` во временный XML под `.1c-dev/`, затем ibcmd |
| `source convert` | import/export через `1cedtcli`, правка `source.format` в манифесте |
| `init` (default IDE target) | Пишет MCP-конфиг, rules, `AGENTS.md`, `.gitignore` |
| `ide configure` | Идемпотентно обновляет MCP/rules/AGENTS; для внешних tools — после `services up` |
| `doctor --fix` | Запускает sync toolchain и повторяет проверку |
| `runtime start --debug` | Клиент с параметрами HTTP-отладки; отдельно нужен `dbgs` / debug API |
| `publish up` (webinst) | Ожидает soft apache из cache (или `ONEC_APACHE_HOME`) |

Desire-list проекта: файл `.1c-dev/tools.yaml` → проверка `1c-dev tools check` (сам `init` файл не создаёт).

## Где что лежит

| Место | Содержимое |
|-------|------------|
| `~/.cache/1c-dev/` | Toolchain jars, soft-deps, индекс docs |
| `~/.local/share/1c-dev/tools/` | Установленные external tools |
| `~/.local/share/1c-dev/services/` | State managed services |
| `~/.local/share/1c-dev/data/` | Данные сервисов (например индекс bsl-search, PID/логи process tools) |
| `.1c-dev/` в проекте | Манифест, runtime ИБ, export EDT, опционально `tools.yaml` |
| `.cursor/` / `.kilo/` | MCP и rules IDE |

## Команда → что нужно

| Хочу | Явно нужно | Часто неявно / soft |
|------|------------|---------------------|
| `metadata.create` (XML) | JDK 25+, xml-gen (sync) | — |
| `metadata.list` / `get` | JDK 25+, md-reader (sync) | — |
| metadata write (EDT) | JDK 25+, md-sparrow (sync) | — |
| `build` / `check` (XML) | `ibcmd`, платформа | — |
| `build` / `check` (EDT) | `ibcmd`, `1cedtcli` | export в `.1c-dev/export/…` |
| `docs.*` | docs-facade (sync) | lazy index |
| `test.*` | платформа, `1cv8`, yaxunit в cache | `yaxunit ensure` |
| `debug.*` | `dbgs`, клиент с debug | session/ping внутри debug API |
| `publish` webinst | soft apache | — |
| `publish` ibsrv | `ibsrv` в окружении платформы | — |
| агент в Cursor/Kilocode | CLI в PATH, `init` или `ide configure` | внешние MCP — отдельно install/up |
| v8std / bsl-ls / bsl-search | `tools install` + `services up` (+ Docker где нужно) | повторный `ide configure` |

## Связанные ADR

- [ADR-013](../adr/013-packaging-toolchain-cache.md) — packaging и cache  
- [ADR-033](../adr/033-external-tools-manager.md) — catalog / services  
- [ADR-029](../adr/029-test-api.md) — YAxUnit / ensure  
- [ADR-017](../adr/017-docs-bsl-context.md) — docs index  
- [ADR-032](../adr/032-edt-source-adapter.md) — EDT  
- [ADR-016](../adr/016-ide-configure.md) — IDE MCP  
