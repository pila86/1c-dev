# md-reader

Thin Java CLI over [MDClasses](https://github.com/1c-syntax/mdclasses) → Metadata IR v1 JSON (ADR-012).

В git — только исходники. Готовый jar **не** в репозитории: ставится в пользовательский cache скриптом fetch (как xml-gen).

```bash
./scripts/fetch-md-reader.sh
# → ~/.cache/1c-dev/tools/md-reader.jar
# Windows: pwsh scripts/fetch-md-reader.ps1
```

Override: `ONEC_MDREADER_JAR`. Нужны JDK 21+ (MDClasses 0.20.0) и Gradle 8+ (Maven Central для зависимостей).

```bash
java -jar ~/.cache/1c-dev/tools/md-reader.jar list <sourceDir>
java -jar ~/.cache/1c-dev/tools/md-reader.jar get <sourceDir> Catalog.Products
java -jar ~/.cache/1c-dev/tools/md-reader.jar find <sourceDir> Товары
```
