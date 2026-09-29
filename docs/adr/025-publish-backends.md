# ADR-025: Publish backends (ibsrv / webinst)

**Статус:** Accepted  
**Дата:** 2026-09-29

## Контекст

Нужна публикация ИБ для веб-клиента / HTTP-сервисов в dev-контуре. Классический путь — Apache/`webinst` (часто нужны права root). Автономный сервер (`ibsrv`) обслуживает одну ИБ по HTTP без внешнего веб-сервера и удобнее для локального AI/dev.

## Решение

1. Продуктовый фасад: CLI/MCP `publish.up` / `publish.down` / `publish.status` / `publish.url` (точные имена при реализации можно слегка уточнить, сохранив группу `publish.*`).
2. Секция манифеста `publish` (schema `"2"`): `default` profile id + `profiles` map.
3. Профиль ссылается на элемент **`runtimes[]`** через `runtime: <id>` (ADR-026).
4. **Must backend:** `ibsrv` — YAML под `.1c-dev/publish/`, управление через `ibcmd server config init` / запуск `ibsrv` (argv заморожены spike [#84](https://github.com/pila86/1c-dev/issues/84)).
5. **Should backend:** `webinst` (`-apache24` и др.) — doctor capability; отсутствие Apache/прав → gap, не hard-fail всего CLI.
6. Тонкие adapters: `adapters/ibsrv/`, `adapters/webinst/` — только subprocess + diagnostics; оркестрация в `core/publish/`.

### Замороженный argv (8.3.25.x, spike #84)

```text
ibcmd server config init \
  --out=.1c-dev/publish/<profile>/ibsrv.yaml \
  --db-path=<abs runtime IB> \
  --http-address=localhost \
  --http-port=<port> \
  --http-base=/ \
  --name=<ib-name>

ibsrv --daemon \
  --config=.1c-dev/publish/<profile>/ibsrv.yaml \
  --data=.1c-dev/publish/<profile>/data \
  --disable-direct-gate \
  --disable-ssh-gate
```

`publish.url` = `http://{server.address}:{server.port}{http.base}` (из YAML).  
Stop: `kill -TERM` по `<data>/lock.pid` (при необходимости KILL + очистка stale lock). Официального `ibsrv stop` нет.

Обязательные флаги для локального HTTP-only: `--disable-direct-gate` / `--disable-ssh-gate` (иначе конфликт с занятыми 1541/1543).  
Повторный `--daemon` на живой `--data` может породить второй процесс при exit 0 — idempotent up делать в `core/publish` по `lock.pid`/порту.

Полный протокол, пример YAML и gaps: [docs/spikes/084-ibcmd-extension-ibsrv.md](../spikes/084-ibcmd-extension-ibsrv.md).

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| ibsrv first, webinst second | Dev без sudo; привычный Apache later | Два адаптера | **Принято** |
| Только Apache/webinst | Один путь | Хрупкий local DX | Отвергнуто как MVP |
| Только ручной default.vrd | Просто | Нет lifecycle API | Отвергнуто |

## Последствия

- Doctor: capabilities `ibsrv`, `webinst`.
- Не смешивать с metadata HTTPService (это объекты конфигурации, не публикация ИБ).

## Связанные решения

- ADR-005, ADR-019, ADR-022, ADR-026
- [M4](../milestones/m4-project-model.md)
- [Spike #84](../spikes/084-ibcmd-extension-ibsrv.md)
