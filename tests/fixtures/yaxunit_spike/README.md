# Fixture: YaXUnit spike (#119)

Минимальный XML-проект для воспроизведения [spike #119](../../../docs/spikes/119-yaxunit-runuittests.md):
пустая конфигурация `main` + два test-extension (`Tests1`, `Tests2`, `purpose: tests`) с модулями YaXUnit.

| Extension | Модуль | Набор | Тесты |
|-----------|--------|-------|-------|
| `Tests1` | `ОМ_Арифметика` | `Арифметика` | `Сложение` (ok), `Деление` (failure), `ДелениеНаНоль` (error), `Пропущенный` (skipped) |
| `Tests1` | `ОМ_Логика` | `Логика` | `ИстинаВерна` (ok) |
| `Tests2` | `ОМ_Строки` | `Строки` | `Конкатенация`, `Длина` (ok) |

Сам YaXUnit в git **не** хранится (Apache-2.0, ~10 МБ XML). Скачайте `YAxUnit-<версия>.cfe`
из [релизов](https://github.com/bia-technologies/yaxunit/releases) и разверните в копии fixture:

```bash
cp -r tests/fixtures/yaxunit_spike /tmp/yax-proj && cd /tmp/yax-proj
1c-dev extension add --id yaxunit --name YAXUNIT --purpose tests --from /path/to/YAxUnit-25.12.cfe
1c-dev build
# extension должны работать без безопасного режима; пути к ibcmd — только абсолютные
for n in YAXUNIT Tests1 Tests2; do
  ibcmd extension update --db-path=$PWD/.1c-dev/runtime/main \
    --data=$PWD/.1c-dev/runtime/ibcmd-data --name=$n --safe-mode=no --unsafe-action-protection=no
done
python run_yaxunit.py --ib .1c-dev/runtime/main --out /tmp/yax-out
python run_yaxunit.py --ib .1c-dev/runtime/main --out /tmp/yax-out --filter '{"extensions": ["Tests2"]}'
```

`run_yaxunit.py` — прототип запуска (`/C"RunUnitTests=<cfg.json>"`, `closeAfterTests`, jUnit → JSON); не часть продукта.
