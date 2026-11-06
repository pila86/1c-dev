# Contributing

## Workflow

1. Выбери issue из актуального [milestone](https://github.com/pila86/1c-dev/milestones) (см. [roadmap](docs/roadmap.md)).
2. Создай ветку: `feature/123-short-description` или `fix/123-short-description`.
3. Реализуй изменения; в коммитах указывай `refs #123`.
4. Открой Pull Request с описанием и ссылкой на issue.

## Формат коммитов

```
<type>(<scope>): <subject>

<body>
```

- **type:** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`
- **scope:** `core`, `cli`, `adapter`, `mcp`, `docs`
- **subject:** кратко на русском языке

Пример:

```
feat(core): добавить загрузку 1c.project.yaml

refs #2
```

## Архитектурные решения

Значимые решения фиксируются в [docs/adr/](docs/adr/) по шаблону [000-template.md](docs/adr/000-template.md).

## Toolchain jars

Рекомендуемый путь (ADR-013 / #48) — без ручных скриптов:

```bash
1c-dev tools sync
```

Кэш: Linux/macOS `~/.cache/1c-dev/tools/`, Windows `%LOCALAPPDATA%\1c-dev\tools\`.

Снятие cache / пакета:

```bash
1c-dev tools clean --yes
1c-dev uninstall --yes                # cache + uv tool uninstall
```

Fallback для разработчиков (те же pin’ы):

```bash
# Linux / macOS
./scripts/fetch-xml-gen.sh
./scripts/fetch-md-reader.sh

# Windows
pwsh scripts/fetch-xml-gen.ps1
pwsh scripts/fetch-md-reader.ps1
```

- xml-gen: JDK 17+, override `ONEC_XMLGEN_JAR`
- md-reader: JDK 21+ (MDClasses 0.20.0), override `ONEC_MDREADER_JAR`
- md-sparrow (M7 / #153, ADR-032 write D): `1c-dev tools sync` кладёт `md-sparrow.jar` в `tools/` (soft, pin 0.6.7); JDK **Temurin 25+**; override `ONEC_MDSPARROW_JAR`. Без jar/JDK → diagnostic `1CS008` / `ENV_UNAVAILABLE` на `apply-mutation`
- yaxunit (M5, ADR-029 §7a): `1c-dev tools sync` кладёт `YAxUnit-<pin>.cfe` в `tools/` (soft); override `ONEC_YAXUNIT_CFE=/path/to/YAxUnit.cfe`. В `project.yaml` не объявляется — runner подключается `1c-dev yaxunit ensure` / `test run`
- apache (publish/webinst, #94): Unix — `./scripts/fetch-apache.sh` или `1c-dev tools sync` (gcc, make, `libpcre2-dev`); Windows — prebuilt zip из манифеста; override `ONEC_APACHE_HOME`

## Тесты

- Unit-тесты — для каждого PR с логикой: `poetry run pytest`.
- Integration-тесты (маркер `integration`) — platform 1С / `ibcmd`, jar xml-gen / md-reader; без них — skip с явным сообщением:
- M3-accept (#52): `poetry run pytest tests/test_m3_acceptance.py -m integration` — CF import round-trip → list/get → ide configure → docs (soft) → build/check; без platform/jars — skip.
- M4-accept (#96): `poetry run pytest tests/test_m4_acceptance.py -m integration` — nested `.1c-dev` → ≥2 configurations + extension → build → `ide --ide-root` → doctor → soft templates / publish ibsrv / publish webinst; без `ibcmd`/xml-gen — skip всего теста; без tmplts / `ibsrv` / `wsap24.so`+Apache — soft-skip соответствующих секций.
- M5-accept (#129): `poetry run pytest tests/test_m5_acceptance.py -m integration` — fixture `yaxunit_spike` (test-extension + `configurations[].tests`) → tools sync / наличие `yaxunit.cfe` → build → `test discover` / `list` / `run` (exit 5 на падающих) / `report` / `runOne`; runner через ensure/cache без ручного `extension add YAXUNIT`; без `ibcmd` / `1cv8` / YaXUnit.cfe — skip.
- M6-accept (#144 / #147): `poetry run pytest tests/test_m6_acceptance.py -m integration` — fixture `debug_spike` → `runtime start --debug --bp` / CLI steps / MCP `debug.*` → wait → variables/eval → continue → stop; плюс `test run --debug --bp` → `debug wait` → `test wait` (yaxunit_spike); без `ibcmd` / `1cv8` / `dbgs` / `DISPLAY` (не-Windows) — skip.
- M7 spike (#149): `poetry run pytest tests/test_edt_cli_smoke.py -m integration` — fixture `edt_spike` → `1cedtcli` export/import + collision rc 204; без `1cedtcli` (`ONEC_EDTCLI` / PATH / `/opt/1C/1CE/components`) — skip (`EDTCLI_SKIP_MESSAGE`). Unit: `tests/test_edtcli_discovery.py`.
- M7 doctor (#151): `1c-dev doctor --output json` → tools.`1cedtcli` + capability `edt` (soft gap `1CD019`); JDK 25+ для md-sparrow — soft `1CD020` (не hard-fail XML-CLI). Unit: `tests/test_doctor.py` (`edtcli` / `md_sparrow_jdk`).
- M7 EdtSourceAdapter (#152): `poetry run pytest tests/test_edt_source_adapter.py tests/test_metadata_read_edt.py` — detect/inspect + `metadata list|get|find` на `edt_spike`; без md-reader jar — skip integration-кейсов.
- M7 md-sparrow (#153): `1c-dev tools sync` → soft `md-sparrow.jar`; override `ONEC_MDSPARROW_JAR`; wrapper `adapters.source.mdsparrow.apply_mutation`. Unit: `tests/test_mdsparrow.py`, `tests/test_mdsparrow_toolchain.py`; smoke mutation на `edt_spike` — skip без jar/JDK 25 (`MD_SPARROW_JDK_SKIP_MESSAGE`).
- M7 metadata write EDT (#154): `metadata.create|update|delete` при `source.format: edt` → md-sparrow apply-mutation (path D). Unit: `tests/test_metadata_write_edt.py`; integration create+attr+update+delete на `edt_spike` — skip без jar/JDK 25.
- M7 build/check EDT (#155): `source.format: edt` → `1cedtcli export` в `.1c-dev/export/<config-id>/` → ibcmd; `check` по file IB после build. Unit: `tests/test_edtcli_client.py`, `tests/test_build_edt.py`; integration `tests/test_build_edt.py -m integration` — skip без `1cedtcli` / ibcmd (`EDTCLI_SKIP_MESSAGE` / `PLATFORM_SKIP_MESSAGE`).
- M7 source.convert (#156): `1c-dev source convert --to=edt|xml` → `1cedtcli` import/export + обновление `configurations[].source.format` (path сохраняется; при path `.` — preserve `.1c-dev`/`.git`). Unit: `tests/test_source_convert.py`, `tests/test_edtcli_client.py` (import); integration round-trip на `edt_spike` — skip без `1cedtcli` (`EDTCLI_SKIP_MESSAGE`). MCP `source.convert` — [#157](https://github.com/pila86/1c-dev/issues/157).
- E-accept (трек E / #71): `poetry run pytest tests/test_e_acceptance.py -m integration` — sample CRUD по волнам E0–E8; без platform/jars — skip.
- Publish ibsrv (#89): `poetry run pytest tests/test_publish_integration.py -m integration` — build → `publish.up` → HTTP 200 на url → down; без `ibcmd`/`ibsrv` — skip.
- Publish webinst (#94): `poetry run pytest tests/test_publish_webinst_integration.py -m integration` — `publish.up` (backend webinst) → url → down; без `wsap24.so` / Apache home (`tools sync` / `ONEC_APACHE_HOME`) — skip. Бинарь `webinst` не обязателен (1c-dev пишет vrd/conf сам).

```bash
poetry run pytest -m integration
```

Перед коммитом: `poetry run ruff check .`, `poetry run mypy`, `poetry run pytest`.

## Issues vs документация

- **GitHub Issues** — рабочий backlog (что делать сейчас).
- **docs/roadmap.md** и **docs/milestones/** — этапы и acceptance criteria (куда идём).
- Не дублируй полный backlog в markdown.
