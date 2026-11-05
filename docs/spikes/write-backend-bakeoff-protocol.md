# Write-backend bake-off — protocol

**Статус:** harness готов (Фаза 1); прогоны S* — ниже.  
**План:** [`.cursor/plans/write_backend_bakeoff_bcf3573c.plan.md`](../../.cursor/plans/write_backend_bakeoff_bcf3573c.plan.md)  
**Вердикт:** [write-backend-bakeoff.md](write-backend-bakeoff.md)

## Header / env (2026-11-05)

| Ключ | Значение |
|------|----------|
| Platform | **8.5.1.1529** (`/opt/1cv8/x86_64/8.5.1.1529`) |
| Dump / format | MetaDataObject `version="2.17"`; `CompatibilityMode=Version8_5_1` |
| JDK A (product) | 21 (doctor default) — xml-gen через `1c-dev` |
| JDK B / bake-off | Temurin **25.0.5+8-LTS** → `~/.jdks/jdk-25.0.5+8` |
| xml-gen | `~/.cache/1c-dev/tools/xml-gen.jar` (pin file `xml-gen-19f67bfed6d1.jar`); sha256 `58c233d5bf2a559de8f5c964b63726ac6369b9408690f72a045f15fe24453da8` |
| md-sparrow | **0.6.7** Platform Tools jar |
| EDT | **2026.2.2+21** (`1cedtcli`); 2023/2024 рядом — не использовать |
| Fixture root | `/home/pila86/work/my/1c-dev/.bakeoff/` (gitignore) |

```bash
export BAKEOFF_JAVA25=/home/pila86/.jdks/jdk-25.0.5+8
export BAKEOFF_MD_SPARROW_JAR=/home/pila86/.config/Code/User/globalStorage/yellow-hammer.1c-platform-tools/md-sparrow/v0.6.7/md-sparrow-0.6.7-all.jar
export BAKEOFF_PLATFORM=8.5.1.1529
export BAKEOFF_EDTCLI=/opt/1C/1CE/components/1c-edt-2026.2.2+21-x86_64/1cedtcli
export BAKEOFF_ROOT=/home/pila86/work/my/1c-dev/.bakeoff
export BAKEOFF_SCHEMA=V2_17
# пути исходников после init:
#   A → $BAKEOFF_ROOT/A/src/BakeoffA
#   B → $BAKEOFF_ROOT/B/src/BakeoffB
SPARROW=("$BAKEOFF_JAVA25/bin/java" -jar "$BAKEOFF_MD_SPARROW_JAR")
```

## Layout

```text
$BAKEOFF_ROOT/
  A/   # xml-gen via 1c-dev; src/BakeoffA; git baseline
  B/   # md-sparrow Designer XML; src/BakeoffB; git baseline
  C/   # bridge XML→EDT (фаза 3) — пусто
  D/   # native .mdo (если S7 OK) — пусто
```

Init (2026-11-05):

```bash
cd "$BAKEOFF_ROOT/A" && poetry -C ~/work/my/1c-dev run 1c-dev init \
  --type configuration --name BakeoffA --config BakeoffA --ide-target none
cd "$BAKEOFF_ROOT/B" && poetry -C ~/work/my/1c-dev run 1c-dev init \
  --type configuration --name BakeoffB --config BakeoffB --ide-target none
# git init + commit baseline в A/ и B/ (для diff noise на S2)
```

## Log entry template

```text
variant: A|B|C|D
scenario: S1…
command(s): …
wall_time_s: …
exit_code: …
artifacts: paths
ibcmd/check: pass|fail|skip
notes: …
```

---

## B: шпаргалка md-sparrow (0.6.7)

Общий вызов: `"${SPARROW[@]}" <cmd> …`. Версия формата: `-v V2_17` / `--schema-version=V2_17`.

### Команды, нужные для S1–S5 / S7

| Scenario | Команды |
|----------|---------|
| S1 create Catalog | `add-md-object` → `cf-md-attribute-add` → (тип/длина) `cf-md-object-set` или `apply-mutation` |
| S2 update | `cf-md-attribute-add`, `cf-md-tabular-section-add`, `cf-md-object-set` |
| S3 delete | `cf-md-object-delete --tag=Catalog --name=…` |
| S5 IR | те же CLI-шаги; считать число вызовов / ручной JSON |
| S7 `.mdo` | `init-empty-cf --format=edt -v V2_17 …` и/или `add-md-object` в EDT-layout |

### Copy-paste: S1 skeleton (Designer XML, без adapter в репо)

```bash
CFG="$BAKEOFF_ROOT/B/src/BakeoffB/Configuration.xml"
OBJ_DIR="$BAKEOFF_ROOT/B/src/BakeoffB/Catalogs"
# 1) Catalog.Products, synonym «Товары»
"${SPARROW[@]}" add-md-object -v "$BAKEOFF_SCHEMA" --type=CATALOG \
  --synonym-ru=Товары "$CFG" Products
# 2) реквизит Article
"${SPARROW[@]}" cf-md-attribute-add -v "$BAKEOFF_SCHEMA" \
  --name=Article "$OBJ_DIR/Products.xml"
# 3) тип String(50) — через JSON set / apply-mutation (уточнить поля на прогоне S1)
# "${SPARROW[@]}" cf-md-object-set -v "$BAKEOFF_SCHEMA" "$OBJ_DIR/Products.xml" /tmp/article-type.json
```

Полный `--help` корневых команд снят 2026-11-05 (`md-sparrow --help`); ключевые usage:

- `add-md-object -v <V2_17> --type=CATALOG [--synonym-ru=…] <Configuration.xml> <Name>`
- `cf-md-attribute-add -v <V> --name=<n> <objectXml>`
- `cf-md-tabular-section-add -v <V> --name=<n> <objectXml>`
- `cf-md-object-set -v <V> <objectXml> <jsonFile>`
- `cf-md-object-delete --tag=Catalog --name=<n> <Configuration.xml> <objectXml>`
- `init-empty-cf -v <V> [--format=designer|edt] <targetRoot>`
- `apply-mutation --params=<ascii-path.json>`

---

## Runs

### Summary

| | A xml-gen | B md-sparrow | C bridge | D mdo+export |
|--|:---------:|:------------:|:--------:|:------------:|
| S1 create | OK 0.98s | OK ~1.9s (3 CLI) | | |
| S2 update | OK (~1.3s/op); dup=warn | OK; dup=exit 2; Qty set fail | | |
| S3 delete | OK 0.83s; ChildObjects clean | OK 0.16s; clean | | |
| S4 platform | OK build+check | OK build+check | | |
| S5 IR fit | 1 CLI `--from-json`; TS synonym OK | ~8 CLI + JSON craft; no native IR | | |
| S6 EDT | n/a | (via D) | OK import/export/build | OK export/build + native create |
| S7 .mdo claim | n/a | **incremental-ok** | — | in play |

### Entries

```text
variant: A
scenario: S1
command(s): poetry run 1c-dev metadata create Catalog.Products --synonym "Товары" --attr "Article:String:50:Артикул" --output json
  (cwd=$BAKEOFF_ROOT/A)
wall_time_s: 0.984
exit_code: 0
artifacts:
  - src/BakeoffA/Catalogs/Products.xml
  - src/BakeoffA/Catalogs/Products/Ext/ManagerModule.bsl
  - src/BakeoffA/Catalogs/Products/Ext/ObjectModule.bsl
  - src/BakeoffA/Configuration.xml (+1 ChildObjects/Catalog)
ibcmd/check: skip
notes: status=ok; synonym Товары; Article String Length=50 synonym Артикул; Configuration.xml diff +1 line; cold CLI ~1s (includes poetry startup)
date: 2026-11-05
```

```text
variant: A
scenario: S2
command(s):
  1) metadata update Catalog.Products --attr "Price:Number:15.2:Цена" --ts "Lines:Строки" --ts-attr "Lines.Qty:Number:15.3:Количество"
  2) metadata update Catalog.Products --op modify-property --value "Synonym=Товары (bakeoff)"
  3) metadata update Catalog.Products --attr "Article:String:50:Артикул"   # duplicate
  4) metadata update Catalog.Products --ts "Lines:Строки"                 # duplicate TS
  (cwd=$BAKEOFF_ROOT/A; after git commit of S1)
wall_time_s: ~1.3 per CLI call (S2.2=1.263, S2.3=1.281, S2.4=1.293; S2.1 similar)
exit_code: 0 (all)
artifacts:
  - src/BakeoffA/Catalogs/Products.xml (diff vs S1: +113 / -1)
ibcmd/check: skip
notes: >
  Price Number(15,2)+синоним Цена OK; ТЧ Lines+синоним Строки OK;
  synonym объекта → «Товары (bakeoff)» OK;
  duplicate attr/TS → status=ok + warning «already exists, skipping» (no-op);
  caveat: ts-attr synonym «Количество» в XML стал «Qty» (IR тоже synonym=Qty) —
  потеря synonym у реквизита ТЧ при sugar --ts-attr.
date: 2026-11-05
```

```text
variant: A
scenario: S3
command(s): poetry run 1c-dev metadata delete Catalog.Products --output json
  (cwd=$BAKEOFF_ROOT/A; after git commit of S2)
wall_time_s: 0.833
exit_code: 0
artifacts:
  - deleted: Catalogs/Products.xml + Ext/*.bsl
  - src/BakeoffA/Configuration.xml (ChildObjects: только Language/Русский; Catalog/Products убран)
ibcmd/check: skip
notes: >
  status=ok; orphan Catalogs/ dir пустой остался; Configuration.xml валидно закрыт;
  diff −504 строк. Состояние для S4 = post-delete (без Products).
date: 2026-11-05
```

```text
variant: A
scenario: S4
command(s):
  1) poetry run 1c-dev build --output json
  2) poetry run 1c-dev check --output json
     env: DISPLAY=:0 GDK_BACKEND=x11 XAUTHORITY=…/mutter-Xwaylandauth.* unset WAYLAND_DISPLAY
  (cwd=$BAKEOFF_ROOT/A; post-delete empty conf)
wall_time_s: build=2.953 (platform duration 2.218); check=2.718 (platform 1.994)
exit_code: build=0; check=0
artifacts:
  - .1c-dev/runtime/BakeoffA/1Cv8.1CD
  - .1c-dev/runtime/check-modules.out («Синтаксических ошибок не обнаружено!»)
ibcmd/check: pass (metadata + modules)
notes: >
  build steps create/import/apply OK.
  Без unset WAYLAND_DISPLAY 1cv8 /CheckModules → exit 255 GTK
  («Unable to initialize GTK+…») — на Wayland-сессии нужен X11-backend.
  Состояние: post-delete (только Language); create→Products в S4 не проверялся.
date: 2026-11-05
```

```text
variant: A
scenario: S5
command(s): 1c-dev metadata create Catalog.ProductsS5 --from-json /tmp/bakeoff-s5-ir.json
  IR: Catalog + synonym + Article String(50) + Price Number(15,2) + TS Lines/Qty+синонимы
wall_time_s: 1.028
exit_code: 0
artifacts:
  - src/BakeoffA/Catalogs/ProductsS5.xml (+ Ext modules)
  - /tmp/bakeoff-s5-ir.json (вход)
ibcmd/check: skip
notes: >
  CLI steps = 1 (`--from-json`); ручной маппинг = 0.
  Внутри: IR → ir_to_xmlgen_dsl → java xml-gen `meta compile`
  + follow-up `modify-ts` для synonym ТЧ (compile map без synonym).
  Round-trip get: object/attr/TS/ts-attr synonyms все сохранились
  (Qty=Количество OK через IR).
  Потери: на S5 IR-пути не видно; на S2 sugar `--ts-attr …:Количество`
  synonym ТЧ-реквизита терялся (→Qty) — разница entrypoint sugar vs IR JSON.
  Ops: JDK 21 (doctor) + xml-gen ~7MB; cold CLI ~1s.
date: 2026-11-05
```

```text
variant: A
scenario: meta (rollup S1–S5)
wall_time_s: S1≈0.98; S2≈1.3/op; S3≈0.83; S4 build≈3.0 check≈2.7; S5≈1.03
diff noise: S2 vs S1 → +113/-1 в одном Products.xml (без CRLF/xmlns shuffle)
ops cost: java21 + xml-gen jar pin; poetry startup в каждом CLI
notes: A закрыт для XML bake-off стороны; ProductsS5 остался после S5 (S3 удалял Products).
```

```text
variant: B
scenario: S1
command(s):
  1) md-sparrow add-md-object -v V2_17 --type=CATALOG --synonym-ru=Товары <Configuration.xml> Products
  2) cf-md-attribute-add -v V2_17 --name=Article <Products.xml>
  3) cf-md-object-get → craft JSON → cf-md-object-set (Article synonym=Артикул, Length=50)
  (java -jar md-sparrow-0.6.7-all.jar; JDK 25; cwd=$BAKEOFF_ROOT/B)
wall_time_s: 0.703 + 0.600 + 0.599 ≈ 1.90
exit_code: 0 (all)
artifacts:
  - src/BakeoffB/Catalogs/Products.xml (без auto Ext/*.bsl — в отличие от A)
  - Configuration.xml ChildObjects +Catalog
ibcmd/check: skip
notes: default attr = String(10)/synonym=Article; тип+синоним только через object-set JSON.
date: 2026-11-05
```

```text
variant: B
scenario: S2
command(s):
  attr-add Price; tabular-section-add Lines; tabular-attribute-add Qty;
  object-get → set (synonym объекта, Price Number(15,2)+Цена, Lines=Строки, Qty=Количество);
  duplicate Article; duplicate Lines
wall_time_s: ~0.6–0.7 per sparrow call
exit_code: mutate=0; duplicate attr/TS → exit 2 («уже существует»)
artifacts: Products.xml (diff vs S1: +532/-134 — шумнее A)
ibcmd/check: skip
notes: >
  object synonym + Lines synonym + Price synonym/type (xs:decimal Digits=15) OK;
  Qty synonym/type через object-set НЕ применились (остались Qty / xs:string(10));
  Price XML содержит NumberQualifiers + хвост StringQualifiers (грязный type node);
  duplicate = hard fail exit 2 (не warning как у A).
date: 2026-11-05
```

```text
variant: B
scenario: S3
command(s): cf-md-object-delete --tag=Catalog --name=Products <Configuration.xml> <Products.xml>
wall_time_s: 0.160
exit_code: 0
artifacts: Products.xml удалён; ChildObjects = Language only
ibcmd/check: skip
notes: быстрее A; состав Configuration.xml корректен.
date: 2026-11-05
```

```text
variant: B
scenario: S4
command(s): 1c-dev build; 1c-dev check (env: unset WAYLAND_DISPLAY, GDK_BACKEND=x11)
wall_time_s: build=2.676; check=2.745
exit_code: 0 / 0
artifacts: runtime BakeoffB; check-modules.out
ibcmd/check: pass (metadata + modules) на post-delete empty conf
notes: как A; create→Products в S4 не в IB (удалён в S3).
date: 2026-11-05
```

```text
variant: B
scenario: S5
command(s): 8× md-sparrow (add-md-object, attr×2, ts, ts-attr, object-set×2, get×…)
  + ручной craft JSON из get (нет --from-json IR)
  цель: Catalog.ProductsS5 ≈ IR A S5
wall_time_s: 5.356 (multi-step)
exit_code: 0
artifacts: src/BakeoffB/Catalogs/ProductsS5.xml
ibcmd/check: skip
notes: >
  CLI steps ≈ 8 + ручной маппинг IR→sparrow DTO (высокий);
  Article String(50)+синоним OK; Price Number OK; Lines synonym OK;
  Qty synonym/type потеряны (object-set не пишет tabular attr);
  native Metadata IR отсутствует — только DTO cf-md-object-*.
  Ops: JDK 25 + jar ~24MB.
date: 2026-11-05
```

---

```text
variant: B / D
scenario: S7
command(s):
  1) md-sparrow init-empty-cf -v V2_17 --format=edt --name=BakeoffD … $BAKEOFF_ROOT/D
  2) apply-mutation --params add-md-object (configurationXml=$D/src/Configuration/Configuration.mdo, type=CATALOG, name=Products)
  3) apply-mutation --params cf-md-attribute-add (objectXml=…/Products.mdo, name=Article)
  negative: add-md-object / cf-md-attribute-add CLI напрямую на .mdo → JAXB Designer XML error
wall_time_s: init=0.513; add≈0.5; attr-mutation OK
exit_code: init=0; mutation add=0; mutation attr=0; direct CLI on .mdo=2
artifacts:
  - D/.project, D/DT-INF/PROJECT.PMF
  - D/src/Configuration/Configuration.mdo (<catalogs>Catalog.Products</catalogs>)
  - D/src/Catalogs/Products/Products.mdo (mdclass:Catalog; synonym Товары; Article attr)
ibcmd/check: skip
notes: >
  Claim = **incremental-ok** (не scaffold-only / не no-mdo).
  Писать .mdo нужно через apply-mutation (EDT router); обычные cf-* CLI — Designer-only.
  cf-md-object-get по .mdo работает. D остаётся в игре для S6.
date: 2026-11-05
```

---

```text
variant: D
scenario: S6
command(s):
  1) 1cedtcli -data _edt-ws-d export --project $BAKEOFF_ROOT/D --configuration-files D_export_xml
  2) 1c-dev project D_ib + copy export → build + check (Wayland X11 env)
  3) apply-mutation add-md-object Partners на Configuration.mdo (create-in-EDT)
wall_time_s: export=16.2; build=2.8; check=2.8; native create=0.45
exit_code: export=0 (лог: Fatal Error premature EOF — артефакты непустые); build=0; check=0
artifacts:
  - D_export_xml/{Configuration.xml, Languages/…, Catalogs/Products.xml} (3 files)
  - D_ib runtime OK; D/src/Catalogs/Partners/Partners.mdo
ibcmd/check: pass
notes: >
  Непустой export; Products в ChildObjects; round-trip ibcmd OK.
  Premature EOF в логе EDT при exit 0 — шум, не must-fail (файлы есть).
  Native create-in-EDT после export — OK (~0.45s).
date: 2026-11-05
```

```text
variant: C
scenario: S6
command(s):
  1) xml-gen: init C_xml + metadata create Catalog.Products (+ Article String50)
  2) 1cedtcli import --version 8.5.1 --configuration-files C_xml/src/BakeoffC --project C
  3) 1cedtcli export --project C --configuration-files C_export_xml
  4) C_ib build + check
  5) create Catalog.Partners в C_xml; re-import в C (нужен fresh -data workspace)
wall_time_s: import≈11.2; export≈12.8; build≈2.7; check≈2.7; reimport≈11.1
exit_code: 0 (re-import в тот же -data → 204 «проект уже существует»; fresh -data → 0)
artifacts:
  - C/src/Catalogs/Products|Partners/*.mdo; C_export_xml (5 files, Article Length=50)
ibcmd/check: pass
notes: >
  Bridge работает; Article(50) сохранился через import/export.
  Повторный create-in-EDT = xml-gen + re-import; тот же EDT workspace ломает
  import (204) — нужен новый -data или иной workflow. Full import ~11s каждый раз.
date: 2026-11-05
```

---

## Verdict (финал 2026-11-05)

**1. XML write: оставить A (xml-gen), не мигрировать на B.**

| Критерий | A | B | Вес |
|----------|---|---|-----|
| S4 correctness | pass | pass | must |
| IR proximity | 1× `--from-json` | ~8 CLI + DTO craft | high → A |
| Incremental / diff / ops | лучше | хуже | med → A |

**2. EDT write: D** (native `.mdo` via md-sparrow `apply-mutation`) + `1cedtcli` только на export; **C** — запасной bridge.

| | C bridge | D native |
|--|:--------:|:--------:|
| S6 export→build/check | pass | pass |
| Create in EDT | full re-import ~11s; workspace quirks | apply-mutation ~0.45s |
| Ops | xml-gen + 1cedtcli import/export | md-sparrow + 1cedtcli export |

**3. Второй write-backend:** XML — нет; EDT — да, позже (wrapper md-sparrow), без замены xml-gen.

Зафиксировано в [write-backend-bakeoff](write-backend-bakeoff.md), [ADR-007](../adr/007-metadata-ir.md), [m7-source-formats](../milestones/m7-source-formats.md).
