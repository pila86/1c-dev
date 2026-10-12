# Fixture: HTTP Debug Protocol spike (#135)

Минимальный XML-проект для [spike #135](../../../docs/spikes/135-http-debug-protocol.md):
конфигурация `DebugSpike` + общий модуль `ОтладкаДемо` с предсказуемой строкой точки останова.

| Поле | Значение |
|------|----------|
| Модуль | `CommonModule.ОтладкаДемо` |
| objectID | `b7e2c4a1-8f3d-4a6e-9c1b-2d5e8f0a3b6c` |
| propertyID (тело CommonModule) | `d5963243-262e-4398-b4d7-fb16d06484f6` |
| Строка BP | **5** (`Значение = 42; // BP-LINE`) — на **исполняемой** строке |
| ApplicationModule objectID | `d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f80` (Configuration uuid) |
| ApplicationModule propertyID | `d22e852a-cf8a-4f77-8ccb-3548e7792bea` |
| Триггер | `ПриНачалеРаботыСистемы` → busy-wait ~10с → `ОтладкаДемо.ВыполнитьДемо()` |
| Alias file IB | `DefAlias` |

```bash
cp -r tests/fixtures/debug_spike /tmp/debug-spike && cd /tmp/debug-spike
1c-dev build
# 1550/1540/1541/1560 на этой машине заняты кластером 1С — не брать вслепую
ss -tln | grep -E ':(1540|1541|1550|1560)\s' || true
python3 run_http_debug.py --ib .1c-dev/runtime/main --port 2550 --no-pause
# только CommonModule BP:
python3 run_http_debug.py --ib .1c-dev/runtime/main --port 2550 --no-pause --common-module-only --eval-expr 'Значение'
```

`run_http_debug.py` — прототип (не продукт). Клиенту нужен `DISPLAY` (на spike: `:0`).
`dbgs` пишет `--notify` в **UTF-16 LE**.

Вход для ADR: [135-http-debug-protocol.md](../../../docs/spikes/135-http-debug-protocol.md) → **ADR-031** (#136; не ADR-030 — уже занят).
