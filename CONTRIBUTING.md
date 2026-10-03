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
- apache (publish/webinst, #94): Unix — `./scripts/fetch-apache.sh` или `1c-dev tools sync` (gcc, make, `libpcre2-dev`); Windows — prebuilt zip из манифеста; override `ONEC_APACHE_HOME`

## Тесты

- Unit-тесты — для каждого PR с логикой: `poetry run pytest`.
- Integration-тесты (маркер `integration`) — platform 1С / `ibcmd`, jar xml-gen / md-reader; без них — skip с явным сообщением:
- M3-accept (#52): `poetry run pytest tests/test_m3_acceptance.py -m integration` — CF import round-trip → list/get → ide configure → docs (soft) → build/check; без platform/jars — skip.
- M4-accept (#96): `poetry run pytest tests/test_m4_acceptance.py -m integration` — nested `.1c-dev` → ≥2 configurations + extension → build → `ide --ide-root` → doctor → soft templates / publish ibsrv / publish webinst; без `ibcmd`/xml-gen — skip всего теста; без tmplts / `ibsrv` / `wsap24.so`+Apache — soft-skip соответствующих секций.
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
