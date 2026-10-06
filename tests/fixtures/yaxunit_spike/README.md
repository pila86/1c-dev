# Fixture: YaXUnit spike (#119)

Минимальный XML-проект для воспроизведения [spike #119](../../../docs/spikes/119-yaxunit-runuittests.md)
и проверки Test API (`1c-dev test …`): пустая конфигурация `main` + два test-extension
(`Tests1`, `Tests2`, `purpose: tests`) с модулями YaXUnit и секцией `configurations[].tests` (suite `unit`).

| Extension | Модуль | Набор | Тесты |
|-----------|--------|-------|-------|
| `Tests1` | `ОМ_Арифметика` | `Арифметика` | `Сложение` (ok), `Деление` (failure), `ДелениеНаНоль` (error), `Пропущенный` (skipped) |
| `Tests1` | `ОМ_Логика` | `Логика` | `ИстинаВерна` (ok) |
| `Tests2` | `ОМ_Строки` | `Строки` | `Конкатенация`, `Длина` (ok) |

Сам YaXUnit в git **не** хранится (Apache-2.0, версия обновляется отдельно) и **не** объявляется
в `project.yaml`: runner (`YAxUnit-<pin>.cfe`) берётся из user cache и подключается в ИБ
неявным `ensure` ([ADR-029 §7a](../../../docs/adr/029-test-api.md)).

```bash
cp -r tests/fixtures/yaxunit_spike /tmp/yax-proj && cd /tmp/yax-proj
1c-dev tools sync                 # YAxUnit.cfe → ~/.cache/1c-dev/tools/ (или ONEC_YAXUNIT_CFE=/path/to.cfe)
1c-dev build                      # конфигурация + Tests1/Tests2
1c-dev test run                   # ensure YAXUNIT + safe-mode off → RunUnitTests; exit 5 (в fixture есть падающие тесты)
1c-dev test run 'ОМ_Строки.Конкатенация'
1c-dev yaxunit ensure             # то же подключение runner без прогона
```

`run_yaxunit.py` — прототип ручного запуска (`/C"RunUnitTests=<cfg.json>"`, `closeAfterTests`, jUnit → JSON);
не часть продукта. Он ожидает, что YAXUNIT и safe-mode уже подготовлены (`1c-dev yaxunit ensure`).
