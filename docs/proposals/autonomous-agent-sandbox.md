# Proposal: автономный агент над 1c-dev (OpenHands + Docker)

**Статус:** draft / фазы 0–2 spike (OH UI готов к пробе)  
**Дата:** 2026-11-26  
**Обновлено:** 2026-11-26 — `1c-agent-base` + `1c-agent-oh`; Agent Canvas compose (`OH_CONVERSATION_IMAGE`); org CA + HTTP(S) proxy; VNC; MCP example. Фаза 3 (issue→PR) — через Automate Canvas после LLM/git tokens. См. [docker/agent/README](../../docker/agent/README.md).  
**Связано:** [overview](../explanation/overview.md), [dependencies](../explanation/dependencies.md), [ADR-005](../adr/005-environment-discovery.md), [ADR-016](../adr/016-ide-configure.md), [ADR-032](../adr/032-edt-source-adapter.md), [ADR-033](../adr/033-external-tools-manager.md), шаблон [AGENTS.md](../../templates/configuration/AGENTS.md)

## Зачем

Сценарий:

1. На вход — URL git-репозитория с 1С-проектом (и позже — текст задачи / issue).
2. Поднимается изолированное окружение: платформа 1С, **EDT (`1cedtcli`)**, `1c-dev`, **Xvfb/VNC**, внешние tools, **OpenHands**.
3. Агент клонирует репо, делает задачу через MCP `1c-dev` (+ bsl-ls и др.), гоняет build/check/test (XML и EDT); клиент `1cv8` может открывать UI на виртуальном дисплее.
4. Пушит ветку и открывает draft MR/PR средствами OpenHands.
5. Человек при необходимости смотрит, что происходит на «рабочем столе» контейнера, через **VNC**.

`1c-dev` уже закрывает «руки и глаза» по 1С (CLI/MCP, adopt, build, check, test, debug, EDT adapter, services).  
Не хватает **outer loop** и **runtime-оболочки**: Docker-образ, display/VNC, OpenHands sandbox, bootstrap. Слои продукта не смешивать: OpenHands = harness, `1c-dev` = tool layer по 1С; инфраструктура агента живёт **в этом же репозитории**, но не размазывает git/MR/LLM по `core/`.

## Рекомендуемый вариант (MVP)

**Базовый образ `1c-agent-base`** = платформа 1С + EDT/`1cedtcli` + JDK(s) + `1c-dev` + **Xvfb / лёгкий DE / x11vnc (или noVNC)** + bootstrap.  
**Sandbox OpenHands** = agent-server поверх `1c-agent-base` (`BASE_IMAGE=…`, [Custom Sandbox](https://docs.openhands.dev/openhands/usage/advanced/custom-sandbox-guide); target `binary` у OH уже тащит VNC/VSCode — стыковать с нашим display-стеком, не плодить два конфликтующих X).  
**Лицензия** — сетевой HASP LM по IP (`nethasp.ini`).  
**Код** — каталог в monorepo `1c-dev` (см. [Где жить коду](#где-жить-коду)).

```text
Оператор / OpenHands UI / CI          VNC-клиент (человек)
    │  REPO, TASK, HASP, tokens              │ :5900 / noVNC
    ▼                                        ▼
┌──────────────────────────────────────────────────────┐
│  OpenHands (host / compose в этом репо)              │
│       │ sandbox image                                │
│       ▼                                              │
│  ┌────────────────────────────────────────────────┐  │
│  │  agent-server (= наш образ)                    │  │
│  │  display: Xvfb (:99) + WM + x11vnc/noVNC       │  │
│  │  startup:                                      │  │
│  │   1. nethasp.ini из HASP_SERVER_ADDR           │  │
│  │   2. поднять Xvfb/VNC                          │  │
│  │   3. doctor (+ 1cedtcli) / toolchain           │  │
│  │   4. clone / init / ide configure / tools      │  │
│  │   5. MCP 1c-dev доступен агенту                │  │
│  │                                                │  │
│  │  OH agent ──MCP──► 1c-dev                      │  │
│  │      │               ├ ibcmd / 1cv8 (DISPLAY)  │  │
│  │      │               ├ 1cedtcli                │  │
│  │      │               └ jars (JDK25)            │  │
│  │      └── git branch / push / draft PR          │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────┬───────────────────────────┘
                           │ UDP/475
                           ▼
                    HASP License Manager
```

### Почему именно так

| Решение | Мотив |
|---------|--------|
| **Всё в репозитории `1c-dev`** | Один продукт: CLI/MCP + образ агента + compose; проще версионировать pin’ы вместе |
| **OpenHands сразу** | Outer loop: clone, ветка, PR/MR, UI, позже issue→PR |
| **EDT сразу** | Реальные репы часто EDT; путь уже в [ADR-032](../adr/032-edt-source-adapter.md) |
| **Xvfb + VNC сразу** | `1cv8`/диалоги платформы нуждаются в DISPLAY; VNC — смотреть и отлаживать «на всякий случай» |
| Платформа+EDT+display на **build**, tools на **first run** | Дистры тяжёлые; jar/catalog — volume-кэш |
| HASP IP на **runtime** | IP не bake’ится в image |
| Git/MR/LLM **не** в `core/` MCP API | Agent-independent граница продукта; harness = OpenHands + `docker/agent` |
| Draft PR + человек на merge | Безопасный DoD |
| Обычный **`docker build`** | Предсказуемо для CI/девопсов; без обязательного buildx |

### Что сознательно не берём в MVP

- Автомерж в `main`.
- Проброс USB-ключа / эмуляторы HASP.
- Vanessa (пока YAxUnit).
- Полный issue→PR Automate — фаза 3 после стабильного e2e.
- Обязательный `docker buildx` / отдельные `--build-context` (только если позже сами попросим).
- Privileged-контейнеры и Docker-in-Docker как default.

### Контракт для девопсов (коротко)

```text
build:   docker build -f docker/agent/Dockerfile.base …  (дистры в distr/, не в git)
run:     docker compose -f docker/agent/compose.yml up
need:    HASP UDP/475, private registry, ≥16GB RAM/sandbox, UI+VNC только internal/VPN
not:     privileged, DinD, USB, secrets/дистры в history образа, latest в проде
tag:     1c-agent-*:onec+edt+gitsha (или digest)
```

## Где подсмотреть у коллег

Не изобретать слои платформы/VNC/EDT с нуля — смотреть проверенные рецепты и переносить **приёмы** (не обязательно git submodule).

| Что нужно нам | Куда смотреть | Что взять глазами |
|---------------|---------------|-------------------|
| Установка платформы в Docker, `distr/`, слои client | [firstBitMarksistskaya/onec-docker](https://github.com/firstBitMarksistskaya/onec-docker) | `client/Dockerfile`, скрипты `build-*.sh`, папка `distr` |
| **Xvfb + VNC + s6** вокруг клиента 1С | тот же onec-docker, слой **`client-vnc`**, [Layers.md](https://github.com/firstBitMarksistskaya/onec-docker/blob/feature/first-bit/Layers.md) | Цепочка `client → s6-overlay → client-vnc`; xfce/xvfb/x11vnc в rootfs |
| `nethasp.ini` | [nethasp.ini.example](https://github.com/firstBitMarksistskaya/onec-docker/blob/feature/first-bit/nethasp.ini.example) | `NH_SERVER_ADDR`, UDP/475, broadcast off |
| EDT / `1cedtcli` в образе | onec-docker `edt/`, [pravets/onec-images](https://github.com/pravets/onec-images) (`edt`, `edtcli`) | `EDT_VERSION`, Java base, `EDT_JAVA_XMX`, PATH к `1cedtcli` |
| Готовый Dev Container «агент + 1С + MCP» | [1C AI Dev Sandbox](https://aitools1c.dev/tools/1c-ai-dev-sandbox/) ([AlekseyUAM/docker_1c_sandbox](https://github.com/AlekseyUAM/docker_1c_sandbox)) | Xvfb, headless платформа, связка MCP/skills; **не** OH outer loop |
| Skills / роли агентов 1С | [SteelMorgan/1c-agent-based-dev-framework](https://github.com/SteelMorgan/1c-agent-based-dev-framework) | AGENTS/skills, SDD/TDD; стык с Cursor/Claude |
| Каталог MCP/tools экосистемы | [Untru/1c-mcp](https://github.com/Untru/1c-mcp) | Обзор v8-runner, sandbox, skills |
| OpenHands custom sandbox + MCP + PR | [OpenHands](https://github.com/OpenHands/OpenHands/), [custom sandbox](https://docs.openhands.dev/openhands/usage/advanced/custom-sandbox-guide), [MCP](https://docs.openhands.dev/openhands/usage/settings/mcp-settings), [issue→PR](https://docs.openhands.dev/openhands/usage/agent-canvas/prebuilt/issue-to-pr) | `BASE_IMAGE` → agent-server; draft PR; VNC в target `binary` |
| CI-агент с 1С (паттерн «агент в Docker») | onec-docker jenkins-agent слои; [jenkins-lib](https://github.com/firstBitMarksistskaya/jenkins-lib) | Метки агентов `edt`, PATH `1cedtcli` |

Итого: **display/VNC/платформа** ≈ First Bit `client-vnc`; **EDT** ≈ их же / pravets `edt`; **агентный контур 1С** ≈ AI Dev Sandbox + SteelMorgan; **outer loop** ≈ OpenHands. Мы склеиваем это вокруг уже существующего MCP `1c-dev`.

## Где жить коду

**В этом репозитории** (`1c-dev`), отдельным деревом, без сваливания в `core/`:

```text
docker/agent/           # или agent/ — уточнить при первом PR
  Dockerfile.base       # платформа + EDT + Xvfb/VNC + 1c-dev
  Dockerfile.openhands  # wrapper/инструкции сборки agent-server
  entrypoint.sh         # nethasp, display, doctor gate
  compose.yml           # пример: OH + sandbox env + ports VNC
  README.md             # сборка, distr, HASP, VNC URL
distr/                  # .gitignore: локальные дистры 1С/EDT (не в git)
```

- Pin `1c-dev` внутри образа = тот же commit/tag, с которого собираем (или `uv tool install` с git SHA).
- Документация: этот proposal + `docker/agent/README.md`; ссылки уже в [docs/README](../README.md) и [roadmap](../roadmap.md).
- В `core/` **не** добавлять: clone, create MR, LLM API. Display/HASP hooks — в `docker/agent`, не в metadata IR.

## Слои Docker-образа

### Build-time (два шага)

**Шаг 1 — `1c-agent-base`**

| Слой | Содержимое |
|------|------------|
| Base | Debian/Ubuntu + git, curl, ca-certificates |
| Platform | Дистр → `ibcmd`/`1cv8`/`dbgs` в PATH |
| EDT | **`1cedtcli` в PATH** (`ONEC_EDTCLI` при необходимости) |
| **Display** | **Xvfb**, лёгкий WM (openbox/xfce — как в референсе), `DISPLAY=:99` |
| **VNC** | **x11vnc** и/или **noVNC** (браузер); порт наружу (например 5900 / 6080) |
| JDK **25+** | Для jar toolchain `1c-dev` (`JAVA_HOME`) |
| JDK EDT | Свой runtime EDT — не подменять `JAVA_HOME` 1c-dev |
| 1c-dev | Из исходников этого репо / wheel CI |
| Bootstrap | nethasp, старт Xvfb/VNC, doctor gate |

**Шаг 2 — OpenHands agent-server**

Сборка **по старинке**: дистры лежат в `distr/` (gitignore), Dockerfile делает `COPY`, дальше обычный `docker build`. Без `buildx` и без отдельных build-context.

```bash
# 1) положить дистры (не коммитить)
#    distr/onec/…  distr/edt/…

# 2) base: платформа + EDT + Xvfb/VNC + 1c-dev
docker build \
  --build-arg ONEC_VERSION=8.3.27.XXXX \
  --build-arg EDT_VERSION=2026.2.x \
  -t 1c-agent-base:8.3.27-edt2026.2 \
  -f docker/agent/Dockerfile.base \
  .

# 3) OpenHands agent-server поверх base
#    (Dockerfile из OH SDK; BASE_IMAGE = наш base)
docker build \
  --build-arg BASE_IMAGE=1c-agent-base:8.3.27-edt2026.2 \
  --target binary \
  -t 1c-agent-oh:8.3.27-edt2026.2 \
  -f …/openhands/agent_server/docker/Dockerfile \
  …
```

В `Dockerfile.base` ожидается что-то вроде `COPY distr/onec/ /tmp/onec-dist/` → silent install → `rm -rf /tmp/onec-dist` (дистр не оставлять в финальном слое без нужды; multi-stage — по желанию, но не обязателен).

Альтернатива в CI: скачать дистр с releases.1c.ru по секретам **на раннере** в `distr/`, затем тот же `docker build` — пароли не попадают в слои образа.

Тег = платформа + edt (+ gitsha/digest). В проде не использовать `latest`.

### Display / VNC (обязательно в MVP)

| Компонент | Роль |
|-----------|------|
| **Xvfb** | Виртуальный framebuffer; `1cv8`, диалоги платформы, часть сценариев runtime/test |
| WM | Минимальный window manager, чтобы окна 1С не вели себя странно |
| **x11vnc** / **noVNC** | Человек подключается и видит тот же `DISPLAY`, что и процессы 1С |
| `DISPLAY=:99` (или как в entrypoint) | Единый для `1cv8` и отладки глазами |

Замечания:

- Сверяться с **onec-docker `client-vnc`** (s6 longrun для xvfb/x11vnc) и с VNC, который уже кладёт OpenHands target `binary` — на spike выбрать **один** стек display, чтобы не поднять два X-сервера.
- Проброс порта в `compose.yml`: `5900:5900` и/или `6080:6080` (noVNC) — **только internal / VPN / SSH-туннель**, не internet-facing LB.
- Пароль VNC через env (`VNC_PASSWORD`).
- Агенту для штатного цикла по-прежнему предпочитать MCP `1c-dev`; VNC — **наблюдение и аварийная диагностика**, не основной UI-автокликер (если позже понадобится computer-use — отдельное решение).

### Java: два мира

| Потребитель | JDK |
|-------------|-----|
| `1c-dev` toolchain | **25+** (`JAVA_HOME`) |
| `1cedtcli` / EDT | Свой (часто 17+) |

`doctor`: green для `ibcmd` и `1cedtcli`.

### Размер и ресурсы

- Образ платформа + EDT + DE/VNC — **десятки ГБ**; private registry.
- EDT: `EDT_JAVA_XMX` / `-Xmx8g+` на крупных export.
- RAM sandbox: ориентир **≥ 16 ГБ** (EDT + ibcmd + OH + X); уточнять на своих конф.

### Runtime volumes / env

| Mount / env | Назначение |
|-------------|------------|
| `HASP_SERVER_ADDR` | → `nethasp.ini` |
| `DISPLAY` / VNC ports | Рабочий стол + просмотр |
| `VNC_PASSWORD` (опц.) | Доступ к VNC |
| Repo / git auth / LLM | Как принято в OH |
| `EDT_JAVA_XMX` | Heap `1cedtcli` |
| volumes cache/share | toolchain + external tools |
| OH workspace | Checkout |

```yaml
environment:
  - AGENT_SERVER_IMAGE_REPOSITORY=1c-agent-oh
  - AGENT_SERVER_IMAGE_TAG=8.3.27-edt2026.2
  - HASP_SERVER_ADDR=10.0.0.50
ports:
  - "5900:5900"   # VNC
  - "6080:6080"   # noVNC, если есть
```

### First-run / conversation start

1. `nethasp.ini` из `HASP_SERVER_ADDR`.
2. Старт **Xvfb + VNC**; export `DISPLAY`.
3. Probe HASP UDP/475 (явный лог).
4. `toolchain sync` при холодном cache.
5. `doctor` — ibcmd + **1cedtcli** (+ soft: display вверх).
6. Checkout → `init` / `ide configure`.
7. Опционально tools/services.
8. Агент OH + MCP `1c-dev`; человек может открыть VNC.

## MCP в OpenHands

- Предпочтительно HTTP/SSE (proxy над `1c-dev mcp`).
- Stdio в sandbox — ок для spike.
- bsl-ls / v8std после `services up` — URL внутри сети sandbox’а.
- Политика: `AGENTS.md`; EDT через `1c-dev`, не ручной EDT UI.

## Лицензирование (HASP)

```ini
[NH_COMMON]
NH_TCPIP=Enabled
NH_IPX=Disabled
NH_NETBIOS=Disabled

[NH_TCPIP]
NH_SERVER_ADDR=<HASP_SERVER_ADDR>
NH_PORT_NUMBER=475
NH_TCPIP_METHOD=UDP
NH_USE_BROADCAST=Disabled
```

Ключ снаружи; USB/эмуляторы — нет; `.lic`+`--net=host` — escape hatch.  
Smoke: `build` (и EDT-export) до старта дорогой conversation.

## Harness: OpenHands (канон)

- Custom agent-server на нашем base (с display/VNC).
- Clone / branch / push / **draft PR**.
- Позже Agent Canvas issue→PR.
- Pin версии OH SDK — API sandbox’а ещё двигается.

## Контракт задачи и Definition of Done

1. MCP `1c-dev` / bsl-ls; `1cv8` при необходимости на `DISPLAY` (Xvfb).
2. Ветка `agent/<slug>` или `openhands/issue-N`.
3. diagnostics → `build` → `check` → `test.*`.
4. Draft MR/PR; красные проверки → draft + отчёт.
5. При сбое UI — смотреть VNC, не гадать вслепую.

| Слой | Владелец |
|------|----------|
| metadata / build / test / debug / EDT | `1c-dev` (`core/`, MCP) |
| Образ, Xvfb/VNC, HASP hook, compose | `docker/agent/` в этом репо |
| Clone / branch / PR | OpenHands |
| Политика кодирования 1С | `AGENTS.md` |

## Фазы внедрения

### Фаза 0 — образ + display + doctor

- `docker/agent/Dockerfile.base`: платформа + EDT + **Xvfb/VNC** + `1c-dev`.
- HASP env; doctor green; ручной `1cv8` виден в VNC; `build`/`check` XML и EDT.

### Фаза 1 — OpenHands e2e

- agent-server поверх base; compose в репо; MCP `1c-dev`.
- Одна задача: clone → правка → build/check → draft PR; параллельно проверить VNC.

### Фаза 2 — кэш и стабилизация

- Volumes; bsl-ls; RAM/Xmx; параллелизм vs HASP; pin OH.

### Фаза 3 — оркестрация

- Issue→PR / Automate; очередь sandbox’ов.

## Альтернативы (кратко)

| Вариант | Вердикт |
|---------|---------|
| **OH + base (платформа+EDT+Xvfb/VNC+1c-dev) в этом репо** | Целевой draft |
| Отдельный репозиторий sandbox | Отвергнуто: всё здесь |
| Без VNC «потом добавим» | Отвергнуто: VNC/Xvfb в MVP |
| Claude Code вместо OH | Только fallback |
| Computer-use как основной путь вместо MCP | Отвергнуто для MVP |

## Открытые вопросы

1. GitHub и/или GitLab для draft MR?
2. Pin’ы: `ONEC_VERSION`, `EDT_VERSION` (ориентир **2026.2.x**), OpenHands SDK.
3. Один display-стек: наш `client-vnc`-подобный **или** VNC из OH `binary` — что оставить?
4. noVNC в образе сразу или только raw VNC на фазе 0?
5. MCP: HTTP-proxy vs stdio на фазе 1?
6. Catalog services: sibling compose / только process bsl-ls? (DinD — нет)
7. Параллельные sandbox’ы vs HASP и RAM?
8. Имя каталога: `docker/agent` vs `agent/`?

## Референсы (краткий список)

Сводка с пояснениями — в разделе [Где подсмотреть у коллег](#где-подсмотреть-у-коллег).

- OpenHands, onec-docker (+ client-vnc, edt, nethasp), onec-images, 1C AI Dev Sandbox, SteelMorgan framework, Untru/1c-mcp
- Внутри продукта: [ADR-032](../adr/032-edt-source-adapter.md), [dependencies](../explanation/dependencies.md)

## Следующий конкретный шаг

1. `./docker/agent/build-oh.sh` + `docker compose -f docker/agent/compose.yml --env-file docker/agent/.env up -d`
2. http://127.0.0.1:3000/canvas — задать LLM, MCP `1c-dev mcp`, прогнать conversation в `1c-agent-oh`
3. Фаза 3: Automate / draft PR при наличии git+LLM tokens
4. Опционально: проброс volume `/certs` и HASP env в каждый conversation-container (если OH не наследует)
