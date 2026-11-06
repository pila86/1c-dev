# Spike #149: EDT fixture + `1cedtcli` export/import smoke

**Дата:** 2026-11-06  
**EDT:** **2026.2.2+21** (`/opt/1C/1CE/components/1c-edt-2026.2.2+21-x86_64/1cedtcli`)  
**md-sparrow:** 0.6.7 (генерация fixture)  
**Issue:** [#149](https://github.com/pila86/1c-dev/issues/149)  
**Волна M7:** 0  
**Граница:** layout EDT + round-trip `1cedtcli` **до** ADR. Продуктового Source Adapter / write path нет. Опора на bake-off Variant **D**: [write-backend-bakeoff](write-backend-bakeoff.md) · [protocol](write-backend-bakeoff-protocol.md).

Fixture: [tests/fixtures/edt_spike/](../../tests/fixtures/edt_spike/README.md).

## TL;DR для ADR (#150) / doctor (#151)

| Вопрос | Ответ |
|--------|-------|
| Layout EDT | Корень проекта = `.project` + `DT-INF/PROJECT.PMF` + `src/Configuration/Configuration.mdo` + объекты `src/<Type>/<Name>/<Name>.mdo` |
| Detect | Наличие `.project` с nature `com._1c.g5.v8.dt.core.V8ConfigurationNature` и/или `Configuration.mdo` под `src/Configuration/` |
| Manifest | `source.format: edt`, `source.path` → **корень EDT-проекта** (в fixture: `.`) |
| `build` path | `1cedtcli export` → Designer XML → существующий ibcmd (платформа `.mdo` не читает) |
| Write path (D) | md-sparrow `apply-mutation` на `.mdo`; обычные `cf-*` CLI — Designer-only |
| Discovery CLI | `ONEC_EDTCLI` → `PATH` → newest `…/1c-edt-*/1cedtcli` под `/opt/1C/1CE/components` (`adapters.edtcli.discover_edtcli`) |
| Мин. EDT | ≥ **2025.1**; 2023/2024 рядом не использовать (bake-off) |
| Workspace | Каждый вызов — **fresh `-data`**; повторный import того же project в тот же `-data` → **rc 204** |
| Export шум | `[Fatal Error] Premature end of file` при **exit 0** и непустом XML — не must-fail |

## 1. Layout fixture

```text
edt_spike/
  .1c-dev/project.yaml          # format: edt, path: .
  .project                      # name=EdtSpike; V8ConfigurationNature
  .settings/…prefs
  DT-INF/PROJECT.PMF            # Runtime-Version: 8.3.24
  src/Configuration/Configuration.mdo
  src/Catalogs/Products/Products.mdo
```

Генерация:

```bash
java -jar md-sparrow-0.6.7-all.jar init-empty-cf -v V2_17 --format=edt --name=EdtSpike <root>
# .project <name> = basename(<root>) — поправить на EdtSpike при необходимости
java -jar … apply-mutation --params=/tmp/add-products.json
# params: {"op":"add-md-object","configurationXml":"…/Configuration.mdo",
#          "type":"CATALOG","name":"Products","synonymRu":"Товары","schemaVersion":"V2_17"}
```

Наблюдение: после mutation синоним в `.mdo` остался `Products` — вручную заменён на «Товары» в fixture (известный gap synonym / bake-off S2).

## 2. Discovery `1cedtcli`

Приоритет (код: `adapters/edtcli/discovery.py`):

1. `ONEC_EDTCLI` — абсолютный путь к бинарю (как `ONEC_XMLGEN_JAR` / `ONEC_YAXUNIT_CFE`)
2. `PATH` (`which 1cedtcli`)
3. Newest install: Linux `/opt/1C/1CE/components/1c-edt-<ver>-*/1cedtcli`

Версия из сегмента каталога (`2026.2.2+21`). Живой `1cedtcli -command version` (~10–15 с cold start) — для doctor soft-probe, не для hot path.

На машине spike рядом лежат 2023.2 / 2024.x / **2026.2.2+21** — для M7 брать только ≥2025.1.

## 3. Команды smoke

Общий вызов:

```bash
1cedtcli -data <fresh-workspace> -timeout <N> -command <cmd> …
```

Без `-command` / `-file` CLI не принимает bare `export`/`import` (Unrecognized option).

### Export (EDT → Designer XML)

```bash
1cedtcli -data "$WS" -timeout 300 -command export \
  --project /abs/path/to/edt_spike \
  --configuration-files /abs/out_xml
```

| Метрика | Значение (2026-11-06) |
|---------|------------------------|
| wall_time | ~16 s |
| exit | **0** |
| артефакты | `Configuration.xml` (version **2.17**), `Languages/Русский.xml`, `Catalogs/Products.xml` |
| stderr | `[Fatal Error] :1:1: Premature end of file.` — шум при непустом export |

Если `--project` ещё не в `-data`, EDT сам импортирует проект в workspace перед export.

### Import (Designer XML → EDT)

```bash
1cedtcli -data "$WS2" -timeout 300 -command import \
  --version 8.5.1 \
  --configuration-files /abs/out_xml \
  --project /abs/new_edt_project
```

| Метрика | Значение |
|---------|----------|
| wall_time | ~10–12 s |
| exit | **0** |
| артефакты | `.project`, `DT-INF/PROJECT.PMF`, `src/Configuration/Configuration.mdo`, `src/Catalogs/Products/Products.mdo` |

`--project-name <name>` создаёт проект в каталоге workspace; повтор с тем же именем в том же `-data` → **204**.

## 4. Коды возврата (официально + наблюдения)

Из `1cedtcli -command help --status-codes`:

| rc | Официально | Наблюдение spike / bake-off |
|----|------------|------------------------------|
| 0 | OK | export/import OK; **и** «шумный» Premature EOF |
| 1 | Не удалось запустить CLI | — |
| 200 | Общая ошибка | смотреть лог `-data` |
| 201 | Script file not found (`-file`) | — |
| 202 | Другой процесс держит workspace | не шарить `-data` |
| 203 | Прервано (таймаут) | поднять `-timeout` |
| **204** | «прекращено с исключением» | **практика:** project already exists in workspace (`edtsh: Проект с именем … уже существует`); fresh `-data` или другое имя/путь |
| 205 | Timeout + kill | — |

Mitigation для продукта (doctor / convert / build): **всегда** новый `-data` (tmpdir) на операцию; не переиспользовать bake-off `_edt-ws-*`.

## 5. Gaps → ADR / волны

| Gap | Следствие |
|-----|-----------|
| `synonymRu` через `apply-mutation` add-md-object не попал в `.mdo` | Contract tests (#158); wrapper md-sparrow (#153/#154) |
| `compatibilityMode` / PMF = 8.3.24 при dump 2.17 / platform 8.5.1 | Уточнить в ADR, нужен ли bump при init |
| Premature EOF при exit 0 | Не считать fail; проверять непустой `Configuration.xml` + ChildObjects |
| rc 204 на collision | Fresh `-data`; сообщение пользователю |
| Doctor capability `edt` | Волна 1 [#151](https://github.com/pila86/1c-dev/issues/151) — reuse `discover_edtcli` |
| Read path Metadata API | Волна 2 [#152](https://github.com/pila86/1c-dev/issues/152) |

## 6. Автотест

```bash
poetry run pytest tests/test_edtcli_discovery.py
poetry run pytest tests/test_edt_cli_smoke.py -m integration
```

Integration skip, если `discover_edtcli().found` is False.

## Ссылки

- [M7 milestone](../milestones/m7-source-formats.md)
- [Bake-off](write-backend-bakeoff.md) · [protocol](write-backend-bakeoff-protocol.md) (S6/S7, Variant D)
- [ADR-007](../adr/007-metadata-ir.md) (XML write); [ADR-032](../adr/032-edt-source-adapter.md) (EDT adapter + write D, Proposed)
- PRD §12 Source API, §49 Format switching, §50 Contract tests, R1 `1cedtcli`
