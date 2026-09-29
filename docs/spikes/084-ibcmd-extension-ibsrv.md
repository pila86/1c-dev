# Spike #84: ibcmd `--extension` + ibsrv lifecycle (argv freeze)

**Дата:** 2026-09-29  
**Платформа:** 8.3.25.1560 (Linux x86_64, `/opt/1cv8/x86_64/8.3.25.1560/`)  
**Issue:** [#84](https://github.com/pila86/1c-dev/issues/84)  
**Граница:** только argv / gaps. Продуктовый API — [#88](https://github.com/pila86/1c-dev/issues/88) (extensions), [#89](https://github.com/pila86/1c-dev/issues/89) (publish).

## Канон режимов

Совместимо с текущим adapter ([ADR-008](../adr/008-ibcmd-build.md) / [ADR-014](../adr/014-ibcmd-import-cf.md)):

| Назначение | Режим |
|------------|--------|
| create / import / apply / load / export / check | `ibcmd infobase …` (+ `infobase config …`) |
| save `.cf` / `.cfe` | `ibcmd config save` (как сейчас) **или** `ibcmd infobase config save` — оба работают |
| list / create / delete extension meta | `ibcmd extension …` |

Top-level `ibcmd config import|apply|export|check` с теми же `--db-path` / `--data` / `--extension` тоже работает; для M4 **не** меняем канон на top-level `config` — остаёмся на `infobase config` + `config save`.

`--extension=<Name>` / `-e <Name>` — **имя расширения** (как `extensions[].name` в schema v2), не `id` манифеста.

---

## A. Extension argv

Общие флаги ИБ (как в build):

```text
--db-path=<runtime.path>
--data=<project>/.runtime/ibcmd-data   # отдельный data-dir, не глобальный standalone-server
```

### A.1 Create (опционально)

```text
ibcmd extension create --db-path=… --data=… --name=<Name> --name-prefix=<Prefix> [--purpose=add-on|customization|patch]
```

- `--name` и `--name-prefix` обязательны.
- Create сам обновляет конфигурацию БД (apply внутри).
- Повторный create с тем же именем → exit **255**, stderr: «Расширение с таким именем уже существует!».

`ibcmd extension list|info|delete --db-path=… --data=… [--name=…]` — рабочие.

### A.2 XML → IB (must)

```text
ibcmd infobase config import --db-path=… --data=… --extension=<Name> <xml_dir>
ibcmd infobase config apply  --db-path=… --data=… --extension=<Name> --force
```

- **Create до import не обязателен:** `import --extension=<Name>` создаёт расширение, если его ещё нет (имя берётся из флага / XML `<Name>`).
- После import без create всё равно нужен **apply**, иначе расширение в list с «пустым» hash-sum / без поколения.
- Рекомендуемый pipeline для #88: import → apply (create — только если нужен явный `--name-prefix` / purpose до появления XML).

### A.3 Export / save / load / check

```text
ibcmd infobase config export --db-path=… --data=… --extension=<Name> <xml_dir>
ibcmd config save           --db-path=… --data=… --extension=<Name> --db <file.cfe>
ibcmd infobase config load  --db-path=… --data=… --extension=<Name> [--force] <file.cfe>
ibcmd infobase config apply --db-path=… --data=… --extension=<Name> --force
ibcmd infobase config check --db-path=… --data=… --extension=<Name> [--force]
```

- `load .cfe --extension=<Name>` **без** предварительного create тоже создаёт расширение.
- Export пустого extension после create даёт `Configuration.xml` + `Roles/` + `ConfigDumpInfo.xml` (`ObjectBelonging=Adopted`, `ConfigurationExtensionPurpose=AddOn`).
- `config check --extension` поддерживается (и на `infobase config check`, и на top-level `config check`).

### A.4 Минимальный XML fixture

- В `Configuration.xml` расширение: `<Name>SpikeExt</Name>`, purpose AddOn, child `Role`.
- Имя в `--extension` должно совпадать с `<Name>` в XML.
- `NamePrefix` в выгрузке может быть пустым после create+export; для scaffold (#88) задавать prefix при `extension create` или в шаблоне.

### A.5 Gaps / ограничения (extension)

| Gap | Деталь |
|-----|--------|
| Нет `--extension` → работает с основной конфигурацией | ожидаемо |
| Дублирующий `extension create` | exit 255 — adapter должен трактовать как already-exists / skip |
| `.cfe` load — should-путь #95 | product: `extension.add --from` = load→apply→export XML в `src/cfe/`; build также умеет `format: cfe` |
| Совместимость режима XML export | spike на 8.3.25; version в XML `2.18` |

---

## B. ibsrv lifecycle argv

### B.1 Init YAML

```text
ibcmd server config init \
  --out=<path>/ibsrv.yaml \
  --db-path=<absolute runtime IB path> \
  --http-address=localhost \
  --http-port=<port> \
  --http-base=/ \
  --name=<ib-name>
```

Пример YAML (сгенерирован init на 8.3.25.1560):

```yaml
server:
  address: localhost
  port: 18314
database:
  path: /abs/path/to/runtime/ib
infobase:
  id: <uuid>
  name: spike84
  distribute-licenses: yes
  schedule-jobs: allow
  disable-local-speech-to-text: no
http:
  base: /
```

`init` **не** пишет порты direct/SSH gates (defaults 1541 / 1543) — их нужно гасить или переносить флагами `ibsrv` при старте.

### B.2 Start

```text
ibsrv --daemon \
  --config=<path>/ibsrv.yaml \
  --data=<path>/publish-data \
  --disable-direct-gate \
  --disable-ssh-gate
```

- `--data` — **отдельный** каталог проекта (рекомендация для #89: `.1c-dev/publish/<profile>/data`), не `~/.1cv8/.../standalone-server`.
- Без `--disable-direct-gate` старт падает, если порт **1541** занят (типичный ragent/кластер): `[ERROR] Ошибка открытия порта '1541'…` / `Address already in use` / exit **255**.
- Аналогично SSH gate (default **1543**) — для HTTP-only publish отключать `--disable-ssh-gate`.
- Альтернатива disable: `--direct-regport=<free>` / `--ssh-port=<free>`.
- После успешного start: `<data>/lock.pid`, HTTP слушает `server.address:server.port`.
- `publish.url` (для #89): `http://{server.address}:{server.port}{http.base}` (при `base: /` → `http://localhost:18314/`). Spike: `GET /` → **HTTP 200**, HTML клиента 1С.

### B.3 Stop / status

Официальной подкоманды `ibsrv stop` в help нет. Рабочий stop:

```text
kill -TERM $(cat <data>/lock.pid)
# при необходимости timeout → kill -KILL
```

- `lock.pid` после kill может **остаться** (stale) — product (#89) должен чистить / проверять `kill -0`.
- SIGTERM иногда не завершает процесс за короткое окно; adapter: TERM → wait → KILL (как runtime client).

### B.4 Idempotent up — gap

Повторный `ibsrv --daemon` на тот же `--data` при живом процессе:

- exit code **0**;
- может породить **второй** процесс ibsrv, при этом `lock.pid` остаётся от первого.

**Вывод для #89:** перед start читать `lock.pid`, проверять живой PID + порт; не вызывать второй daemon вслепую.

### B.5 Gaps / ограничения (ibsrv)

| Gap | Деталь |
|-----|--------|
| Нет бинаря `ibsrv` | doctor capability gap (#89), не hard-fail всего CLI |
| Занят 1541/1543 | обязательны `--disable-direct-gate` / `--disable-ssh-gate` или свободные порты |
| Занят HTTP port | fatal / fail start |
| File IB only (MVP) | spike на file `--db-path`; server DBMS не проверялся |
| `--daemon` без disable gates | silent/fail в зависимости от занятых портов — фиксировать в diagnostics |

---

## Рекомендации для волны 1

**#88 (extensions):** в `adapters/platform_ibcmd/client.py` добавить optional `extension: str | None` в import/apply/save/load/export/check; pipeline build: configuration, затем foreach extension `import`+`apply` с `--extension=name`. `extension list` → `ibcmd extension list`.

**#89 (publish):**  
1. `ibcmd server config init --out=.1c-dev/publish/…/ibsrv.yaml --db-path=<runtime.abs> …`  
2. `ibsrv --daemon --config=… --data=.1c-dev/publish/…/data --disable-direct-gate --disable-ssh-gate`  
3. status/url из yaml + `lock.pid` + HTTP probe  
4. down: TERM/KILL по pid, cleanup stale lock

---

## Воспроизведение (scratch)

Каталог spike (не в git): `/tmp/1c-dev-spike-84/` — conf-project через `1c-dev project init`, build, затем команды выше на `ibcmd`/`ibsrv` 8.3.25.1560.
