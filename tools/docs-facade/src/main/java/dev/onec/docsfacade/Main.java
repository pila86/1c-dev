package dev.onec.docsfacade;

import com.github._1c_syntax.bsl.context.PlatformContextGrabber;
import com.github._1c_syntax.bsl.context.api.Context;
import com.github._1c_syntax.bsl.context.api.ContextEnum;
import com.github._1c_syntax.bsl.context.api.ContextEnumValue;
import com.github._1c_syntax.bsl.context.api.ContextEvent;
import com.github._1c_syntax.bsl.context.api.ContextKind;
import com.github._1c_syntax.bsl.context.api.ContextLanguageKeyword;
import com.github._1c_syntax.bsl.context.api.ContextMethod;
import com.github._1c_syntax.bsl.context.api.ContextMethodSignature;
import com.github._1c_syntax.bsl.context.api.ContextName;
import com.github._1c_syntax.bsl.context.api.ContextProperty;
import com.github._1c_syntax.bsl.context.api.ContextProvider;
import com.github._1c_syntax.bsl.context.api.ContextQueryElement;
import com.github._1c_syntax.bsl.context.api.ContextSignatureParameter;
import com.github._1c_syntax.bsl.context.api.ContextType;
import com.github._1c_syntax.bsl.context.api.QueryContextProvider;
import com.github._1c_syntax.bsl.context.platform.PlatformGlobalContext;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Thin CLI over bsl-context → on-disk docs index (ADR-017).
 *
 * <pre>
 *   docs-facade ensure  --index-dir DIR --platform-version VER (--hbk FILE | --platform-bin DIR) [--force]
 *   docs-facade search  --index-dir DIR --query Q [--limit N]
 *   docs-facade get     --index-dir DIR --name NAME
 * </pre>
 */
public final class Main {

  static final String FACADE_PIN = "bsl-context-0.10.0";

  private static final Gson GSON = new GsonBuilder().disableHtmlEscaping().create();
  private static final String META_FILE = "meta.json";
  private static final String INDEX_FILE = "index.json";

  private Main() {
  }

  public static void main(String[] args) {
    if (args.length < 1) {
      usageAndExit();
    }
    String command = args[0];
    Map<String, String> opts = parseOpts(args);
    try {
      switch (command) {
        case "ensure" -> cmdEnsure(opts);
        case "search" -> cmdSearch(opts);
        case "get" -> cmdGet(opts);
        default -> usageAndExit();
      }
    } catch (FailException ex) {
      System.out.println(ex.json);
      System.exit(1);
    } catch (Exception ex) {
      try {
        fail("1CX005", "docs-facade: " + ex.getMessage());
      } catch (FailException failEx) {
        System.out.println(failEx.json);
        System.exit(1);
      }
    }
  }

  private static void usageAndExit() {
    System.err.println(
        "Usage:\n"
            + "  docs-facade ensure  --index-dir DIR --platform-version VER"
            + " (--hbk FILE | --platform-bin DIR) [--force]\n"
            + "  docs-facade search  --index-dir DIR --query Q [--limit N]\n"
            + "  docs-facade get     --index-dir DIR --name NAME"
    );
    System.exit(2);
  }

  private static Map<String, String> parseOpts(String[] args) {
    Map<String, String> opts = new LinkedHashMap<>();
    for (int i = 1; i < args.length; i++) {
      String a = args[i];
      if ("--force".equals(a)) {
        opts.put("force", "true");
        continue;
      }
      if (a.startsWith("--") && i + 1 < args.length && !args[i + 1].startsWith("--")) {
        opts.put(a.substring(2), args[++i]);
      } else if (a.startsWith("--")) {
        opts.put(a.substring(2), "true");
      }
    }
    return opts;
  }

  private static Path requireIndexDir(Map<String, String> opts) {
    String raw = opts.get("index-dir");
    if (raw == null || raw.isBlank()) {
      fail("1CX003", "Требуется --index-dir");
    }
    return Path.of(raw).toAbsolutePath().normalize();
  }

  private static void cmdEnsure(Map<String, String> opts) throws IOException {
    Path indexDir = requireIndexDir(opts);
    String platformVersion = opts.get("platform-version");
    if (platformVersion == null || platformVersion.isBlank()) {
      fail("1CX003", "Требуется --platform-version");
    }
    Path hbk = resolveHbk(opts);
    boolean force = "true".equals(opts.get("force"));

    Files.createDirectories(indexDir);
    Path metaPath = indexDir.resolve(META_FILE);
    Path indexPath = indexDir.resolve(INDEX_FILE);

    long mtime = Files.getLastModifiedTime(hbk).toMillis();
    long size = Files.size(hbk);

    boolean fresh = !force
        && Files.isRegularFile(metaPath)
        && Files.isRegularFile(indexPath)
        && metaMatches(metaPath, platformVersion, hbk, mtime, size);

    if (fresh) {
      JsonObject root = new JsonObject();
      root.addProperty("status", "ok");
      JsonObject index = new JsonObject();
      index.addProperty("version", platformVersion);
      index.addProperty("built", false);
      index.addProperty("path", indexDir.toString());
      root.add("index", index);
      System.out.println(GSON.toJson(root));
      return;
    }

    PlatformContextGrabber grabber = PlatformContextGrabber.fromHbk(hbk, null);
    grabber.parse();
    ContextProvider provider = grabber.getProvider();
    QueryContextProvider queryProvider = grabber.getQueryProvider();

    List<JsonObject> entries = new ArrayList<>();
    for (Context ctx : provider.getContexts()) {
      addContextEntries(entries, ctx);
    }
    PlatformGlobalContext global = provider.getGlobalContext();
    if (global != null) {
      addGlobalEntries(entries, global);
    }
    if (queryProvider != null) {
      for (ContextQueryElement el : queryProvider.getElements()) {
        entries.add(queryElementEntry(el));
      }
    }

    JsonObject indexRoot = new JsonObject();
    JsonArray arr = new JsonArray();
    entries.forEach(arr::add);
    indexRoot.add("entries", arr);
    Files.writeString(indexPath, GSON.toJson(indexRoot), StandardCharsets.UTF_8);

    JsonObject meta = new JsonObject();
    meta.addProperty("platformVersion", platformVersion);
    meta.addProperty("facadePin", FACADE_PIN);
    meta.addProperty("hbkPath", hbk.toString());
    meta.addProperty("hbkMtime", mtime);
    meta.addProperty("hbkSize", size);
    meta.addProperty("builtAt", Instant.now().toString());
    meta.addProperty("entryCount", entries.size());
    Files.writeString(metaPath, GSON.toJson(meta), StandardCharsets.UTF_8);

    JsonObject root = new JsonObject();
    root.addProperty("status", "ok");
    JsonObject index = new JsonObject();
    index.addProperty("version", platformVersion);
    index.addProperty("built", true);
    index.addProperty("path", indexDir.toString());
    index.addProperty("entryCount", entries.size());
    root.add("index", index);
    System.out.println(GSON.toJson(root));
  }

  private static Path resolveHbk(Map<String, String> opts) {
    String hbkRaw = opts.get("hbk");
    if (hbkRaw != null && !hbkRaw.isBlank()) {
      Path hbk = Path.of(hbkRaw).toAbsolutePath().normalize();
      if (!Files.isRegularFile(hbk)) {
        fail("1CX002", "HBK не найден: " + hbk);
      }
      return hbk;
    }
    String binRaw = opts.get("platform-bin");
    if (binRaw != null && !binRaw.isBlank()) {
      Path bin = Path.of(binRaw).toAbsolutePath().normalize();
      Path candidate = bin.resolve("shcntx_ru.hbk");
      if (!Files.isRegularFile(candidate) && bin.getFileName() != null
          && !"bin".equalsIgnoreCase(bin.getFileName().toString())) {
        candidate = bin.resolve("bin").resolve("shcntx_ru.hbk");
      }
      if (!Files.isRegularFile(candidate)) {
        fail("1CX002", "HBK не найден рядом с platform-bin: " + bin);
      }
      return candidate;
    }
    fail("1CX002", "Требуется --hbk или --platform-bin");
    return null; // unreachable
  }

  private static boolean metaMatches(
      Path metaPath,
      String platformVersion,
      Path hbk,
      long mtime,
      long size
  ) {
    try {
      JsonObject meta = JsonParser.parseString(Files.readString(metaPath, StandardCharsets.UTF_8))
          .getAsJsonObject();
      return platformVersion.equals(meta.has("platformVersion")
              ? meta.get("platformVersion").getAsString() : "")
          && FACADE_PIN.equals(meta.has("facadePin") ? meta.get("facadePin").getAsString() : "")
          && hbk.toString().equals(meta.has("hbkPath") ? meta.get("hbkPath").getAsString() : "")
          && mtime == (meta.has("hbkMtime") ? meta.get("hbkMtime").getAsLong() : -1L)
          && size == (meta.has("hbkSize") ? meta.get("hbkSize").getAsLong() : -1L);
    } catch (Exception ex) {
      return false;
    }
  }

  private static void addContextEntries(List<JsonObject> entries, Context ctx) {
    String kind = kindLabel(ctx.kind());
    String nameRu = nameRu(ctx.name());
    String nameEn = nameEn(ctx.name());
    String qname = nameRu;

    JsonObject top = baseEntry(qname, nameRu, nameEn, kind, null, ctx.description());
    top.addProperty("sinceVersion", nullToEmpty(ctx.sinceVersion()));
    top.addProperty("deprecatedSinceVersion", nullToEmpty(ctx.deprecatedSinceVersion()));
    top.add("examples", stringArray(ctx.examples()));
    top.add("seeAlso", stringArray(ctx.seeAlso()));
    if (ctx instanceof ContextLanguageKeyword keyword) {
      top.addProperty("category", keyword.category() == null ? "" : keyword.category().name());
    }
    entries.add(top);

    if (ctx instanceof ContextType type) {
      for (ContextMethod method : type.methods()) {
        entries.add(methodEntry(nameRu, method));
      }
      for (ContextProperty property : type.properties()) {
        entries.add(propertyEntry(nameRu, property));
      }
      for (ContextEvent event : type.events()) {
        entries.add(eventEntry(nameRu, event));
      }
    }
    if (ctx instanceof ContextEnum enumeration) {
      for (ContextEnumValue value : enumeration.values()) {
        entries.add(enumValueEntry(nameRu, value));
      }
    }
  }

  private static void addGlobalEntries(List<JsonObject> entries, PlatformGlobalContext global) {
    String owner = nameRu(global.name());
    JsonObject top = baseEntry(owner, owner, nameEn(global.name()), "global", null, "");
    top.addProperty("sinceVersion", nullToEmpty(global.sinceVersion()));
    entries.add(top);
    for (ContextMethod method : global.methods()) {
      entries.add(methodEntry(owner, method));
    }
    for (ContextProperty property : global.properties()) {
      entries.add(propertyEntry(owner, property));
    }
  }

  private static JsonObject methodEntry(String owner, ContextMethod method) {
    String nameRu = nameRu(method.name());
    String qname = owner + "." + nameRu;
    JsonObject entry = baseEntry(qname, nameRu, nameEn(method.name()), "method", owner, method.description());
    entry.addProperty("sinceVersion", nullToEmpty(method.sinceVersion()));
    entry.addProperty("deprecatedSinceVersion", nullToEmpty(method.deprecatedSinceVersion()));
    entry.add("examples", stringArray(method.examples()));
    entry.add("seeAlso", stringArray(method.seeAlso()));
    entry.addProperty("hasReturnValue", method.hasReturnValue());
    entry.addProperty("returnValueDescription", nullToEmpty(method.returnValueDescription()));
    JsonArray sigs = new JsonArray();
    for (ContextMethodSignature sig : method.signatures()) {
      JsonObject s = new JsonObject();
      s.addProperty("syntaxText", nullToEmpty(sig.syntaxText()));
      s.addProperty("description", nullToEmpty(sig.description()));
      JsonArray params = new JsonArray();
      for (ContextSignatureParameter p : sig.parameters()) {
        JsonObject pj = new JsonObject();
        pj.addProperty("name", nameRu(p.name()));
        pj.addProperty("nameEn", nameEn(p.name()));
        pj.addProperty("required", p.isRequired());
        pj.addProperty("defaultValue", nullToEmpty(p.defaultValue()));
        params.add(pj);
      }
      s.add("parameters", params);
      sigs.add(s);
    }
    entry.add("signatures", sigs);
    return entry;
  }

  private static JsonObject propertyEntry(String owner, ContextProperty property) {
    String nameRu = nameRu(property.name());
    String qname = owner + "." + nameRu;
    JsonObject entry = baseEntry(
        qname, nameRu, nameEn(property.name()), "property", owner, property.description()
    );
    entry.addProperty("sinceVersion", nullToEmpty(property.sinceVersion()));
    entry.addProperty("deprecatedSinceVersion", nullToEmpty(property.deprecatedSinceVersion()));
    entry.add("examples", stringArray(property.examples()));
    entry.add("seeAlso", stringArray(property.seeAlso()));
    if (property.accessMode() != null) {
      entry.addProperty("accessMode", property.accessMode().name());
    }
    return entry;
  }

  private static JsonObject eventEntry(String owner, ContextEvent event) {
    String nameRu = nameRu(event.name());
    String qname = owner + "." + nameRu;
    JsonObject entry = baseEntry(qname, nameRu, nameEn(event.name()), "event", owner, event.description());
    entry.addProperty("sinceVersion", nullToEmpty(event.sinceVersion()));
    return entry;
  }

  private static JsonObject enumValueEntry(String owner, ContextEnumValue value) {
    String nameRu = nameRu(value.name());
    String qname = owner + "." + nameRu;
    return baseEntry(qname, nameRu, nameEn(value.name()), "enumValue", owner, value.description());
  }

  private static JsonObject queryElementEntry(ContextQueryElement el) {
    String nameRu = nameRu(el.name());
    String nameEn = nameEn(el.name());
    JsonObject entry = baseEntry(nameRu, nameRu, nameEn, "queryElement", null, el.description());
    if (el.category() != null) {
      entry.addProperty("category", el.category().name());
    }
    entry.add("examples", stringArray(el.examples()));
    return entry;
  }

  private static JsonObject baseEntry(
      String qualifiedName,
      String name,
      String nameEn,
      String kind,
      String owner,
      String description
  ) {
    JsonObject o = new JsonObject();
    o.addProperty("qualifiedName", qualifiedName);
    o.addProperty("name", name);
    o.addProperty("nameEn", nameEn == null ? "" : nameEn);
    o.addProperty("kind", kind);
    if (owner != null) {
      o.addProperty("owner", owner);
    }
    String desc = description == null ? "" : description;
    o.addProperty("description", desc);
    o.addProperty("snippet", snippet(desc));
    return o;
  }

  private static String snippet(String description) {
    if (description == null || description.isBlank()) {
      return "";
    }
    String oneLine = description.replace('\n', ' ').replace('\r', ' ').trim();
    return oneLine.length() <= 200 ? oneLine : oneLine.substring(0, 200) + "…";
  }

  private static String kindLabel(ContextKind kind) {
    if (kind == null) {
      return "type";
    }
    return switch (kind) {
      case PRIMITIVE_TYPE -> "primitive";
      case TYPE -> "type";
      case COLLECTION -> "collection";
      case ENUM -> "enum";
      case GLOBAL_CONTEXT -> "global";
      case LANGUAGE_KEYWORD -> "keyword";
    };
  }

  private static void cmdSearch(Map<String, String> opts) throws IOException {
    Path indexDir = requireIndexDir(opts);
    String query = opts.get("query");
    if (query == null || query.isBlank()) {
      fail("1CX003", "Требуется --query");
    }
    int limit = 20;
    if (opts.containsKey("limit")) {
      try {
        limit = Integer.parseInt(opts.get("limit"));
      } catch (NumberFormatException ex) {
        fail("1CX003", "Некорректный --limit");
      }
    }
    List<JsonObject> entries = loadEntries(indexDir);
    String needle = query.toLowerCase(Locale.ROOT);
    List<Hit> hits = new ArrayList<>();
    for (JsonObject e : entries) {
      double score = scoreEntry(e, needle);
      if (score > 0) {
        hits.add(new Hit(score, e));
      }
    }
    hits.sort(Comparator.comparingDouble((Hit h) -> h.score).reversed()
        .thenComparing(h -> h.entry.get("qualifiedName").getAsString()));
    if (hits.size() > limit) {
      hits = hits.subList(0, limit);
    }

    JsonObject root = new JsonObject();
    root.addProperty("status", "ok");
    JsonArray arr = new JsonArray();
    for (Hit hit : hits) {
      JsonObject h = new JsonObject();
      h.addProperty("name", hit.entry.get("qualifiedName").getAsString());
      h.addProperty("kind", hit.entry.get("kind").getAsString());
      if (hit.entry.has("owner") && !hit.entry.get("owner").isJsonNull()) {
        h.addProperty("owner", hit.entry.get("owner").getAsString());
      }
      h.addProperty("score", hit.score);
      h.addProperty("snippet", hit.entry.has("snippet") ? hit.entry.get("snippet").getAsString() : "");
      arr.add(h);
    }
    root.add("hits", arr);
    System.out.println(GSON.toJson(root));
  }

  private static double scoreEntry(JsonObject e, String needle) {
    String qn = lower(e, "qualifiedName");
    String name = lower(e, "name");
    String nameEn = lower(e, "nameEn");
    if (qn.equals(needle) || name.equals(needle) || nameEn.equals(needle)) {
      return 3.0;
    }
    if (qn.startsWith(needle) || name.startsWith(needle) || nameEn.startsWith(needle)) {
      return 2.0;
    }
    if (qn.contains(needle) || name.contains(needle) || nameEn.contains(needle)) {
      return 1.0;
    }
    String snippet = lower(e, "snippet");
    if (snippet.contains(needle)) {
      return 0.5;
    }
    return 0;
  }

  private static void cmdGet(Map<String, String> opts) throws IOException {
    Path indexDir = requireIndexDir(opts);
    String name = opts.get("name");
    if (name == null || name.isBlank()) {
      fail("1CX003", "Требуется --name");
    }
    List<JsonObject> entries = loadEntries(indexDir);
    String needle = name.toLowerCase(Locale.ROOT);

    JsonObject found = null;
    // 1) Exact qualifiedName / nameEn as full identity
    for (JsonObject e : entries) {
      if (lower(e, "qualifiedName").equals(needle)
          || lower(e, "nameEn").equals(needle) && !e.has("owner")) {
        found = e;
        break;
      }
    }
    // 2) Top-level entry whose short name matches (types, keywords, …)
    if (found == null) {
      for (JsonObject e : entries) {
        if (e.has("owner") && !e.get("owner").isJsonNull()) {
          continue;
        }
        if (lower(e, "name").equals(needle) || lower(e, "nameEn").equals(needle)) {
          found = e;
          break;
        }
      }
    }
    // 3) Any member / entry short name
    if (found == null) {
      for (JsonObject e : entries) {
        if (lower(e, "name").equals(needle) || lower(e, "nameEn").equals(needle)) {
          found = e;
          break;
        }
      }
    }
    if (found == null) {
      fail("1CX004", "Запись не найдена: " + name);
    }
    JsonObject root = new JsonObject();
    root.addProperty("status", "ok");
    root.add("entry", found);
    System.out.println(GSON.toJson(root));
  }

  private static List<JsonObject> loadEntries(Path indexDir) throws IOException {
    Path indexPath = indexDir.resolve(INDEX_FILE);
    if (!Files.isRegularFile(indexPath)) {
      fail("1CX003", "Индекс не найден: " + indexPath + " (сначала ensure)");
    }
    JsonObject root = JsonParser.parseString(Files.readString(indexPath, StandardCharsets.UTF_8))
        .getAsJsonObject();
    JsonArray arr = root.getAsJsonArray("entries");
    List<JsonObject> entries = new ArrayList<>();
    if (arr != null) {
      for (JsonElement el : arr) {
        entries.add(el.getAsJsonObject());
      }
    }
    return entries;
  }

  private static String lower(JsonObject o, String key) {
    if (!o.has(key) || o.get(key).isJsonNull()) {
      return "";
    }
    return o.get(key).getAsString().toLowerCase(Locale.ROOT);
  }

  private static String nameRu(ContextName name) {
    return name == null ? "" : nullToEmpty(name.getName());
  }

  private static String nameEn(ContextName name) {
    return name == null ? "" : nullToEmpty(name.getAlias());
  }

  private static String nullToEmpty(String s) {
    return s == null ? "" : s;
  }

  private static JsonArray stringArray(List<String> values) {
    JsonArray arr = new JsonArray();
    if (values != null) {
      for (String v : values) {
        if (v != null && !v.isBlank()) {
          arr.add(v);
        }
      }
    }
    return arr;
  }

  private record Hit(double score, JsonObject entry) {
  }

  private static final class FailException extends RuntimeException {
    final String json;

    FailException(String json) {
      this.json = json;
    }
  }

  private static void fail(String code, String message) {
    JsonObject err = new JsonObject();
    err.addProperty("status", "error");
    err.addProperty("code", code);
    err.addProperty("message", message);
    throw new FailException(GSON.toJson(err));
  }
}
