# Contributing

## Workflow

1. Выбери issue из [milestone M1](https://github.com/pila86/1c-dev/milestone/1) (или другого актуального milestone).
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

## Toolchain: xml-gen

Для `1c-dev metadata create` нужен jar xml-gen (ADR-007). Один раз:

```bash
# Linux / macOS
./scripts/fetch-xml-gen.sh

# Windows
pwsh scripts/fetch-xml-gen.ps1
```

Требуется JDK 17+. Override пути: `ONEC_XMLGEN_JAR`.

## Тесты

- Unit-тесты — для каждого PR с логикой.
- Integration-тесты M1 — требуют установленной платформы 1С; при отсутствии — skip с явным сообщением.
- Integration metadata — требуют jar xml-gen (после `fetch-xml-gen`); иначе skip.

## Issues vs документация

- **GitHub Issues** — рабочий backlog (что делать сейчас).
- **docs/roadmap.md** и **docs/milestones/** — этапы и acceptance criteria (куда идём).
- Не дублируй полный backlog в markdown.
