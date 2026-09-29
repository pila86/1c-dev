# ADR-025: Publish backends (ibsrv / webinst)

**Статус:** Accepted  
**Дата:** 2026-09-29  
**Обновлено:** 2026-09-29 — webinst + user-owned Apache в cache (#94); `--backend` / MCP `backend` с ensure `local-<backend>`; default backend = webinst

## Контекст

Нужна публикация ИБ для веб-клиента / HTTP-сервисов в dev-контуре. Классический путь — системный Apache/`webinst` (часто нужны права root на `/etc`). Автономный сервер (`ibsrv`) обслуживает одну ИБ по HTTP без внешнего веб-сервера и удобнее для локального AI/dev. Для should-пути Apache нужен **свой** httpd в user-cache без sudo.

## Решение

1. Продуктовый фасад: CLI/MCP `publish.up` / `publish.down` / `publish.status` / `publish.url` (точные имена при реализации можно слегка уточнить, сохранив группу `publish.*`).
2. Секция манифеста `publish` (schema `"2"`): `default` profile id + `profiles` map.
3. Профиль ссылается на элемент **`runtimes[]`** через `runtime: <id>` (ADR-026).
4. **Default backend (новые проекты):** `webinst` + **user-owned Apache** в toolchain cache ([ADR-013](013-packaging-toolchain-cache.md)) — профиль `local-webinst` создаётся при первом `configuration.add` / runtime; порт по умолчанию 8315. Системный `/etc/apache2` **не** используем.
5. **Альтернативный backend:** `ibsrv` — YAML под `.1c-dev/publish/`, управление через `ibcmd server config init` / запуск `ibsrv` (argv заморожены spike [#84](https://github.com/pila86/1c-dev/issues/84)); профиль `local-ibsrv` через `--backend ibsrv`.
6. Тонкие adapters: `adapters/ibsrv/`, `adapters/webinst/`, `adapters/apache/` — только subprocess + diagnostics; оркестрация в `core/publish/`.
7. **Выбор способа публикации:** CLI/MCP флаг `--backend` / `backend` (`ibsrv`|`webinst`):
   - если есть профиль с этим backend — выбрать его (предпочтение `publish.default`, иначе `local-<backend>`, иначе первый по id);
   - на `publish.up` при отсутствии — **ensure** профиля `local-<backend>` в `project.yaml` (runtime = global default); `default` не меняем, если уже задан;
   - без флага — используется `publish.default` (для новых проектов — `local-webinst`).
   - `--profile` + `--backend`: backends должны совпасть, иначе ошибка.

### Замороженный argv (ibsrv, 8.3.25.x, spike #84)

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

### Замороженный argv (webinst + user Apache, #94)

Layout:

```text
~/.cache/1c-dev/tools/apache/     # soft tools sync / ONEC_APACHE_HOME / fetch-apache.sh
  bin/httpd
  modules/*.so
  conf/mime.types
  .1c-dev-apache.json

.1c-dev/publish/<profile>/
  httpd.conf   # ServerRoot / Listen / PidFile / LoadModule wsap24
  www/         # webinst -dir + default.vrd
  logs/
  httpd.pid
```

Default port **8315** (не 80 — bind без root). URL: `http://127.0.0.1:{port}/{wsdir}`.

```text
# scaffold user-owned httpd.conf + default.vrd + Alias/Directory
# (бинарь webinst на Linux требует root даже с -confPath — не вызываем)
# default.vrd: httpServices publishByDefault + publishExtensionsByDefault

<apache_home>/bin/httpd \
  -f <.1c-dev/publish/<profile>/httpd.conf> \
  -d <.1c-dev/publish/<profile>>

# stop: TERM/KILL по httpd.pid
# down: снять Alias/Directory + default.vrd
```

Модуль `wsap24.so` — из каталога платформы (рядом с `ibcmd` / `webinst`). Бинарь httpd — из cache (`1c-dev tools sync` собирает ASF sources на Unix или качает prebuilt; fallback `./scripts/fetch-apache.sh` / `ONEC_APACHE_HOME`). Публикацию (vrd + conf-блоки) пишет сам 1c-dev в формате, совместимом с выводом `webinst -apache24`.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| webinst (Apache) default, ibsrv optional | HTTP-сервисы / веб-клиент как в проде; httpd в user-cache без sudo | Два адаптера | **Принято** |
| Только Apache/webinst | Один путь | Нет лёгкого ibsrv fallback | Отвергнуто |
| ibsrv first (исторически MVP) | Dev без sudo | Нет полноценных HTTP-сервисов как у Apache | Superseded |
| Только ручной default.vrd | Просто | Нет lifecycle API | Отвергнуто |
| Системный `/etc/apache2` + sudo | Знакомый ops | Права, ломает DX | **Отвергнуто для #94** |
| User-owned httpd в cache | Без sudo; conf в `.1c-dev/publish/` | Soft sync / OS gaps | **Принято (#94)** |

## Последствия

- Doctor: capabilities `ibsrv`, `webinst` (requires `webinst` + `apache`).
- Soft toolchain component `apache` в [ADR-013](013-packaging-toolchain-cache.md).
- Не смешивать с metadata HTTPService (это объекты конфигурации, не публикация ИБ).

## Связанные решения

- ADR-005, ADR-013, ADR-019, ADR-022, ADR-026
- [M4](../milestones/m4-project-model.md)
- [Spike #84](../spikes/084-ibcmd-extension-ibsrv.md)
- Issues [#89](https://github.com/pila86/1c-dev/issues/89), [#94](https://github.com/pila86/1c-dev/issues/94)
