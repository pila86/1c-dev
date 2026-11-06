# Fixture: EDT source spike (#149)

Минимальный EDT-проект для [spike #149](../../../docs/spikes/149-edt-source-adapter.md)
и последующих unit/E2E M7: `Configuration.mdo` + `.project` / `DT-INF` + один справочник
`Catalog.Products` (синоним «Товары»).

| Поле | Значение |
|------|----------|
| Имя проекта (`.project`) | `EdtSpike` |
| Source format | `edt` (`.1c-dev/project.yaml` → `configurations[main].source.path: .`) |
| Schema dump | MetaDataObject **2.17** (после `1cedtcli export`) |
| Compatibility (`.mdo` / PMF) | `8.3.24` (дефолт `md-sparrow init-empty-cf --format=edt -v V2_17`) |
| Объект | `Catalog.Products` → `src/Catalogs/Products/Products.mdo` |

Сгенерировано: `md-sparrow` **0.6.7** (`init-empty-cf --format=edt` + `apply-mutation` `add-md-object`).
Синоним «Товары» в `.mdo` выставлен вручную (поле `synonymRu` в mutation на прогоне spike
не записалось — gap bake-off S2 / input для ADR).

```bash
# discovery
ONEC_EDTCLI=/opt/1C/1CE/components/1c-edt-2026.2.2+21-x86_64/1cedtcli   # optional override

# smoke export → Designer XML (fresh -data!)
WS=$(mktemp -d)
OUT=$(mktemp -d)
"$ONEC_EDTCLI" -data "$WS" -timeout 300 -command export \
  --project "$(pwd)/tests/fixtures/edt_spike" \
  --configuration-files "$OUT"
ls "$OUT"/{Configuration.xml,Catalogs/Products.xml,Languages/*}

# smoke import XML → EDT (другой fresh -data)
WS2=$(mktemp -d)
PROJ=$(mktemp -d)
"$ONEC_EDTCLI" -data "$WS2" -timeout 300 -command import \
  --version 8.5.1 \
  --configuration-files "$OUT" \
  --project "$PROJ"
```

Автотест: `poetry run pytest tests/test_edt_cli_smoke.py -m integration`
(без `1cedtcli` — skip). Вход для ADR: [149-edt-source-adapter.md](../../../docs/spikes/149-edt-source-adapter.md).
