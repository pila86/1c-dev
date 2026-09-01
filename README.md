# 1C Dev Runtime

Agent-independent toolchain и API-слой для AI-native разработки на платформе 1С.

## Текущий фокус

**Milestone M1: catalog via agent** — агент создаёт конфигурацию с одним справочником через MCP без ручного Конфигуратора.

- [M1: acceptance criteria и workflow](docs/milestones/m1-catalog-via-agent.md)
- [Roadmap](docs/roadmap.md)
- [Issues (M1)](https://github.com/pila86/1c-dev/milestone/1)
- [PRD v0.1](1c-dev-runtime-PRD-v0.1.md)

## Быстрый старт (после реализации M1)

```bash
# Установка runtime (зависит от ADR-001: Python / Go / Rust)
# ...

# Создание проекта
1c-dev init --type configuration

# Проверка окружения
1c-dev doctor

# MCP для агента
1c-dev mcp
```

## Документация

| Документ | Описание |
|----------|----------|
| [PRD v0.1](1c-dev-runtime-PRD-v0.1.md) | Полная спецификация |
| [Roadmap](docs/roadmap.md) | Этапы разработки |
| [CONTRIBUTING](CONTRIBUTING.md) | Как участвовать |
| [ADR](docs/adr/README.md) | Архитектурные решения |

## Принцип

> Agent-independent + IDE-independent + source-format-independent.

Runtime — фасад над существующей 1С developer ecosystem, а не её замена.
