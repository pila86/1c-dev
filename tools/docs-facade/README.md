# docs-facade

Thin CLI over [bsl-context](https://github.com/1c-syntax/bsl-context) for `1c-dev docs.*` (ADR-017).

```bash
./gradlew fatJar
java -jar build/libs/docs-facade.jar ensure --index-dir ~/.cache/1c-dev/docs/8.3.27 \
  --platform-version 8.3.27 --hbk /path/to/shcntx_ru.hbk
```

Requires JDK 21+. Prefer `1c-dev tools sync` to install into the user cache.
