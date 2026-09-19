package dev.onec.mdreader;

import com.github._1c_syntax.bsl.mdclasses.Configuration;
import com.github._1c_syntax.bsl.mdclasses.MDClasses;
import com.github._1c_syntax.bsl.mdo.AccumulationRegister;
import com.github._1c_syntax.bsl.mdo.Attribute;
import com.github._1c_syntax.bsl.mdo.Catalog;
import com.github._1c_syntax.bsl.mdo.Document;
import com.github._1c_syntax.bsl.mdo.Enum;
import com.github._1c_syntax.bsl.mdo.InformationRegister;
import com.github._1c_syntax.bsl.mdo.MD;
import com.github._1c_syntax.bsl.mdo.TabularSection;
import com.github._1c_syntax.bsl.mdo.children.EnumValue;
import com.github._1c_syntax.bsl.types.MdoReference;
import com.github._1c_syntax.bsl.types.MultiLanguageString;
import com.github._1c_syntax.bsl.types.ValueType;
import com.github._1c_syntax.bsl.types.ValueTypeDescription;
import com.github._1c_syntax.bsl.types.qualifiers.NumberQualifiers;
import com.github._1c_syntax.bsl.types.qualifiers.StringQualifiers;
import com.github._1c_syntax.bsl.types.value.PrimitiveValueType;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * Thin CLI over MDClasses → Metadata IR v1 JSON (ADR-012).
 *
 * Usage:
 *   md-reader list &lt;sourceDir&gt;
 *   md-reader get &lt;sourceDir&gt; &lt;QName&gt;
 *   md-reader find &lt;sourceDir&gt; &lt;query&gt;
 */
public final class Main {

  private static final Set<String> FULL_IR_TYPES = Set.of(
      "Catalog",
      "Document",
      "Enum",
      "InformationRegister",
      "AccumulationRegister"
  );

  private static final Gson GSON = new GsonBuilder().disableHtmlEscaping().create();

  private Main() {
  }

  public static void main(String[] args) {
    if (args.length < 2) {
      usageAndExit();
    }
    String command = args[0];
    Path sourceDir = Path.of(args[1]).toAbsolutePath().normalize();
    try {
      if (!Files.isDirectory(sourceDir)) {
        fail("1CM001", "Каталог исходников не найден: " + sourceDir);
      }
      Configuration configuration = (Configuration) MDClasses.createConfiguration(sourceDir);
      switch (command) {
        case "list" -> emitOkObjects(listObjects(configuration, null));
        case "find" -> {
          if (args.length < 3) {
            usageAndExit();
          }
          emitOkObjects(listObjects(configuration, args[2]));
        }
        case "get" -> {
          if (args.length < 3) {
            usageAndExit();
          }
          emitOkObject(getObject(configuration, args[2]));
        }
        default -> usageAndExit();
      }
    } catch (FailException ex) {
      System.out.println(ex.json);
      System.exit(1);
    } catch (Exception ex) {
      try {
        fail("1CM007", "md-reader: " + ex.getMessage());
      } catch (FailException failEx) {
        System.out.println(failEx.json);
        System.exit(1);
      }
    }
  }

  private static void usageAndExit() {
    System.err.println("Usage: md-reader list|get|find <sourceDir> [qname|query]");
    System.exit(2);
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

  private static void emitOkObjects(List<JsonObject> objects) {
    JsonObject root = new JsonObject();
    root.addProperty("status", "ok");
    JsonArray arr = new JsonArray();
    objects.forEach(arr::add);
    root.add("objects", arr);
    System.out.println(GSON.toJson(root));
  }

  private static void emitOkObject(JsonObject object) {
    JsonObject root = new JsonObject();
    root.addProperty("status", "ok");
    root.add("object", object);
    System.out.println(GSON.toJson(root));
  }

  private static List<JsonObject> listObjects(Configuration configuration, String query) {
    String needle = query == null ? null : query.toLowerCase(Locale.ROOT);
    List<JsonObject> result = new ArrayList<>();
    for (MD md : configuration.getChildren()) {
      JsonObject summary = toSummary(md);
      if (needle != null) {
        String name = summary.get("name").getAsString().toLowerCase(Locale.ROOT);
        String synonym = summary.has("synonym")
            ? summary.get("synonym").getAsString().toLowerCase(Locale.ROOT)
            : "";
        String qname = summary.get("qname").getAsString().toLowerCase(Locale.ROOT);
        if (!name.contains(needle) && !synonym.contains(needle) && !qname.contains(needle)) {
          continue;
        }
      }
      result.add(summary);
    }
    result.sort(Comparator.comparing(o -> o.get("qname").getAsString()));
    return result;
  }

  private static JsonObject getObject(Configuration configuration, String qname) {
    Optional<MD> found = configuration.findChild(MdoReference.create(qname));
    if (found.isEmpty()) {
      // try case-insensitive scan
      found = configuration.getChildren().stream()
          .filter(md -> md.getMdoRef().equalsIgnoreCase(qname))
          .findFirst();
    }
    if (found.isEmpty()) {
      fail("1CM008", "Объект не найден: " + qname);
    }
    MD md = found.get();
    String type = typeName(md);
    if (FULL_IR_TYPES.contains(type)) {
      return toFullIr(md);
    }
    return toSummary(md);
  }

  private static JsonObject toSummary(MD md) {
    JsonObject obj = new JsonObject();
    String type = typeName(md);
    String name = md.getName();
    obj.addProperty("type", type);
    obj.addProperty("name", name);
    obj.addProperty("qname", type + "." + name);
    String synonym = synonymOf(md.getSynonym());
    if (synonym != null) {
      obj.addProperty("synonym", synonym);
    }
    return obj;
  }

  private static String typeName(MD md) {
    String fromRef = md.getMdoReference().getType().nameEn();
    if (fromRef != null && !fromRef.isBlank() && !"Unknown".equalsIgnoreCase(fromRef)) {
      return fromRef;
    }
    return md.getClass().getSimpleName();
  }

  private static String synonymOf(MultiLanguageString synonym) {
    if (synonym == null || synonym.isEmpty()) {
      return null;
    }
    String ru = synonym.get("ru");
    if (ru != null && !ru.isBlank()) {
      return ru;
    }
    String any = synonym.getAny();
    return any == null || any.isBlank() ? null : any;
  }

  @SuppressWarnings("unchecked")
  private static JsonObject toFullIr(MD md) {
    JsonObject obj = toSummary(md);
    // drop qname from full IR (ADR-011 object shape uses type+name); keep for convenience? ADR says type/name/synonym
    // Keep qname — useful for agents; ADR list requires it, get is full IR — qname is harmless extra.
    if (md instanceof Catalog catalog) {
      obj.add("attributes", attributesArray((List<Attribute>) (List<?>) catalog.getAttributes()));
      obj.add("tabularSections", tabularSectionsArray((List<?>) catalog.getTabularSections()));
    } else if (md instanceof Document document) {
      obj.add("attributes", attributesArray((List<Attribute>) (List<?>) document.getAttributes()));
      obj.add("tabularSections", tabularSectionsArray((List<?>) document.getTabularSections()));
    } else if (md instanceof Enum enumeration) {
      obj.add("values", enumValuesArray((List<EnumValue>) (List<?>) enumeration.getEnumValues()));
    } else if (md instanceof InformationRegister register) {
      obj.add("dimensions", attributesArray((List<Attribute>) (List<?>) register.getDimensions()));
      obj.add("resources", attributesArray((List<Attribute>) (List<?>) register.getResources()));
    } else if (md instanceof AccumulationRegister register) {
      obj.add("dimensions", attributesArray((List<Attribute>) (List<?>) register.getDimensions()));
      obj.add("resources", attributesArray((List<Attribute>) (List<?>) register.getResources()));
    }
    return obj;
  }

  private static JsonArray attributesArray(List<? extends Attribute> attributes) {
    JsonArray arr = new JsonArray();
    if (attributes == null) {
      return arr;
    }
    for (Attribute attribute : attributes) {
      arr.add(attributeToJson(attribute));
    }
    return arr;
  }

  private static JsonArray tabularSectionsArray(List<?> sections) {
    JsonArray arr = new JsonArray();
    if (sections == null) {
      return arr;
    }
    for (Object sectionObj : sections) {
      if (!(sectionObj instanceof TabularSection section)) {
        continue;
      }
      JsonObject ts = new JsonObject();
      ts.addProperty("name", section.getName());
      String synonym = synonymOf(section.getSynonym());
      if (synonym != null) {
        ts.addProperty("synonym", synonym);
      }
      @SuppressWarnings("unchecked")
      List<Attribute> attrs = (List<Attribute>) (List<?>) section.getAttributes();
      ts.add("attributes", attributesArray(attrs));
      arr.add(ts);
    }
    return arr;
  }

  private static JsonArray enumValuesArray(List<EnumValue> values) {
    JsonArray arr = new JsonArray();
    if (values == null) {
      return arr;
    }
    for (EnumValue value : values) {
      JsonObject item = new JsonObject();
      item.addProperty("name", value.getName());
      String synonym = synonymOf(value.getSynonym());
      if (synonym != null) {
        item.addProperty("synonym", synonym);
      }
      arr.add(item);
    }
    return arr;
  }

  private static JsonObject attributeToJson(Attribute attribute) {
    JsonObject obj = new JsonObject();
    obj.addProperty("name", attribute.getName());
    String synonym = synonymOf(attribute.getSynonym());
    if (synonym != null) {
      obj.addProperty("synonym", synonym);
    }
    Map<String, Object> mapped = mapValueType(attribute.getValueType());
    for (Map.Entry<String, Object> entry : mapped.entrySet()) {
      Object val = entry.getValue();
      if (val instanceof Number number) {
        obj.addProperty(entry.getKey(), number);
      } else if (val instanceof Boolean bool) {
        obj.addProperty(entry.getKey(), bool);
      } else if (val != null) {
        obj.addProperty(entry.getKey(), String.valueOf(val));
      }
    }
    return obj;
  }

  /**
   * Map MDClasses ValueTypeDescription → IR v1 attribute type fields.
   * Composite: prefer Ref, else first primitive.
   */
  private static Map<String, Object> mapValueType(ValueTypeDescription description) {
    Map<String, Object> result = new LinkedHashMap<>();
    if (description == null || description.isEmpty()) {
      result.put("type", "String");
      result.put("length", 10);
      return result;
    }

    List<ValueType> types = description.getTypes();
    ValueType chosen = chooseType(types);
    if (chosen == null) {
      result.put("type", "String");
      result.put("length", 10);
      return result;
    }

    if (chosen == PrimitiveValueType.STRING) {
      result.put("type", "String");
      result.put("length", stringLength(description));
      return result;
    }
    if (chosen == PrimitiveValueType.NUMBER) {
      result.put("type", "Number");
      int[] ps = numberPrecisionScale(description);
      result.put("precision", ps[0]);
      result.put("scale", ps[1]);
      return result;
    }
    if (chosen == PrimitiveValueType.BOOLEAN) {
      result.put("type", "Boolean");
      return result;
    }
    if (chosen == PrimitiveValueType.DATE) {
      result.put("type", "Date");
      return result;
    }

    String en = chosen.nameEn();
    String refQname = refQnameFromTypeName(en);
    if (refQname != null) {
      result.put("type", "Ref");
      result.put("reference", refQname);
      return result;
    }

    result.put("type", "String");
    result.put("length", 10);
    return result;
  }

  private static ValueType chooseType(List<ValueType> types) {
    if (types == null || types.isEmpty()) {
      return null;
    }
    for (ValueType type : types) {
      String en = type.nameEn();
      if (en != null && en.contains("Ref.")) {
        return type;
      }
    }
    for (ValueType type : types) {
      if (type == PrimitiveValueType.STRING
          || type == PrimitiveValueType.NUMBER
          || type == PrimitiveValueType.BOOLEAN
          || type == PrimitiveValueType.DATE) {
        return type;
      }
    }
    return types.get(0);
  }

  private static String refQnameFromTypeName(String typeName) {
    if (typeName == null) {
      return null;
    }
    // CatalogRef.Products → Catalog.Products
    int idx = typeName.indexOf("Ref.");
    if (idx > 0) {
      String kind = typeName.substring(0, idx);
      String name = typeName.substring(idx + 4);
      if (!kind.isBlank() && !name.isBlank()) {
        return kind + "." + name;
      }
    }
    return null;
  }

  private static int stringLength(ValueTypeDescription description) {
    for (Object qualifier : description.getQualifiers()) {
      if (qualifier instanceof StringQualifiers sq) {
        long len = sq.getLength();
        return len > 0 ? (int) len : 10;
      }
    }
    return 10;
  }

  private static int[] numberPrecisionScale(ValueTypeDescription description) {
    for (Object qualifier : description.getQualifiers()) {
      if (qualifier instanceof NumberQualifiers nq) {
        return new int[]{nq.getPrecision(), nq.getScale()};
      }
    }
    return new int[]{15, 2};
  }
}
