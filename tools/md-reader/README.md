# md-reader

Thin Java CLI over [MDClasses](https://github.com/1c-syntax/mdclasses) → Metadata IR v1 JSON (ADR-012).

В git — исходники и **Gradle Wrapper** (8.10.2). Готовый jar **не** в репозитории: ставится в пользовательский cache через `1c-dev tools sync` или скрипт fetch.

```bash
1c-dev tools sync
# или вручную:
./scripts/fetch-md-reader.sh
# → ~/.cache/1c-dev/tools/md-reader.jar
# Windows: pwsh scripts/fetch-md-reader.ps1
```

Override: `ONEC_MDREADER_JAR`. Нужны JDK 21+ (MDClasses 0.20.0). Системный Gradle не требуется — сборка идёт через `./gradlew`.

```bash
java -jar ~/.cache/1c-dev/tools/md-reader.jar list <sourceDir>
java -jar ~/.cache/1c-dev/tools/md-reader.jar get <sourceDir> Catalog.Products
java -jar ~/.cache/1c-dev/tools/md-reader.jar find <sourceDir> Товары
```
