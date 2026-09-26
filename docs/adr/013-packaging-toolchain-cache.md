# ADR-013: Packaging (`uv tool`) / user cache / pin toolchain

**Статус:** Accepted  
**Дата:** 2026-09-26

## Контекст

В [ADR-001](001-language-core-cli.md) distribution (`pipx` / `uv tool` / PyInstaller) была отложена: для M1 достаточно Poetry-checkout monorepo. [M3 Product adopt](../milestones/m3-product-adopt.md) требует must-путь: CLI в PATH **без** клонирования репозитория рядом с продуктом, плюс идемпотентная докачка нативных jar toolchain (xml-gen, md-reader/MDClasses, BSL LS, docs facade) в user cache.

Сейчас jars кладутся вручную через `scripts/fetch-*.sh` в de-facto cache (`~/.cache/1c-dev/tools/`, Windows `%LOCALAPPDATA%\1c-dev\tools\`), pin’ы размазаны по constants и скриптам, override — `ONEC_XMLGEN_JAR` / `ONEC_MDREADER_JAR`. Нужно зафиксировать публичный UX установки, layout cache, единый манифест pin/checksum и приоритет env — контракт для `#48` (`1c-dev install`).

## Решение

### Must UX: установка CLI

```bash
uv tool install git+https://github.com/pila86/1c-dev
# или из локального wheel:
# uv tool install ./dist/1c_dev-*.whl

1c-dev --version
1c-dev install          # jars → user cache (реализация: #48)
1c-dev doctor
```

- **Must:** `uv tool install` (git и/или wheel) → entrypoint `1c-dev` в PATH пользователя.
- Python-пакет — оркестратор; jars **не** внутри wheel, а в user cache после `install`.
- Разработка в monorepo остаётся на **Poetry** (`pyproject.toml` + poetry-core уже даёт wheel, совместимый с uv).
- Имя post-install команды: **`1c-dev install`** — идемпотентный bootstrap toolchain.

### Layout user cache

Корень — **cache** (артефакты пересобираемые). `~/.local/share` в M3 **не** вводим.

```text
Linux/macOS:  ${XDG_CACHE_HOME:-~/.cache}/1c-dev/
Windows:      %LOCALAPPDATA%\1c-dev\

  tools/
    xml-gen.jar / xml-gen-{pin}.jar
    md-reader.jar / md-reader-{pin}.jar
    bsl-language-server.jar / bsl-language-server-{ver}.jar
    docs-facade.jar / docs-facade-{pin}.jar   # имя фасада bsl-context — #48 / #51
  docs/                                      # lazy index по platform.version (#51)
```

Совпадает с текущим `tools_cache_dir()` в `adapters/source/xmlgen/resolve.py` (каталог `tools/`).

### Манифест toolchain

Единый источник pin’ов в репозитории (и в wheel): **`toolchain/manifest.yaml`**.

Минимальные поля компонента:

| Поле | Назначение |
|------|------------|
| `id` | Идентификатор (`xml-gen`, `md-reader`, `bsl-language-server`, `docs-facade`, …) |
| `artifact` | Stable filename в `tools/` (например `xml-gen.jar`) |
| `pin` | Версия / commit / tag |
| `source` | Откуда брать (git commit, GitHub release, Maven) |
| `sha256` | Опционально; при mismatch — diagnostic + re-fetch |
| `min_java` | Минимальный major JDK |
| `env` | Имя env-override (`ONEC_XMLGEN_JAR`, …) |

Реализация чтения манифеста и докачки — `#48`. Constants/скрипты могут временно дублировать pin, SoT — манифест.

### Resolve order

1. **Env override** (`ONEC_*_JAR`) — приоритет над cache  
2. Stable name в `tools/` (`xml-gen.jar`, …)  
3. Pinned name в `tools/` (`xml-gen-{pin}.jar`, …)

При смене pin в манифесте `1c-dev install` обновляет артефакт. Нет сети / JDK → structured diagnostic; CLI остаётся usable для команд без jar.

### Out of scope / later (не acceptance M3)

| Вариант | Вердикт |
|---------|---------|
| `uv tool install` | **Принято (must)** |
| Poetry checkout | только для разработки |
| pipx | альтернатива / later |
| Публикация на PyPI | later |
| Single-binary (PyInstaller и т.п.) | later, не must |

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| `uv tool` + `1c-dev install` + cache | PATH без monorepo; jars отдельно; совпадает с M3 | нужен uv; jars не «из коробки» после только tool install | **Принято** |
| Только Poetry / clone рядом с продуктом | привычный dev UX | не product adopt | Отвергнуто для user install |
| pipx как must | знакомый инструмент | дублирует uv; не acceptance M3 | Отложено (альтернатива) |
| Jar’ы в wheel / `third_party/` | один шаг install | размер, лицензии, бинарь в дистрибутиве | Отвергнуто (как в ADR-007 B) |
| `~/.local/share` для jars | «данные приложения» | лишний корень; артефакты регенерируемы | Отвергнуто для M3 |
| PyInstaller single-binary | один файл | сложность, JDK всё равно нужен | Later |

## Последствия

- README / onboarding M3: must-путь `uv tool install` → `1c-dev install` (не только `poetry run` + ручные `fetch-*.sh`) — `#49`.
- `#48` реализует `install` по этому layout и манифесту; fetch-скрипты остаются fallback / для разработчиков.
- Doctor (`#49`) проверяет каждый jar toolchain и отсылает к `install` / `--fix`.
- ADR-007 / ADR-012: cache path и env-override сохраняются; SoT pin смещается к `toolchain/manifest.yaml`.

## Связанные решения

- [ADR-001](001-language-core-cli.md) — язык / Poetry; packaging перенесено сюда
- [ADR-007](007-metadata-ir.md) — xml-gen + cache
- [ADR-012](012-metadata-read-mdclasses.md) — md-reader + cache
- [M3 Product adopt](../milestones/m3-product-adopt.md)
- Issue [#45](https://github.com/pila86/1c-dev/issues/45) (этот ADR)
- Issue [#48](https://github.com/pila86/1c-dev/issues/48) (`1c-dev install`)
