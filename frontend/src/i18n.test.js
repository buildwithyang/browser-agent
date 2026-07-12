import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";

import {
  LANGUAGES,
  LanguageContext,
  LanguageToggle,
  detectLang,
  resolveMessage,
} from "./i18n.jsx";
import { messages } from "./strings.js";

function shape(value) {
  if (Array.isArray(value)) return value.map(shape);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, shape(child)]));
  }
  return typeof value;
}

describe("language detection", () => {
  test("saved language takes priority over browser languages", () => {
    const storage = { getItem: () => "zh" };
    expect(detectLang(storage, ["fr-FR", "en-US"])).toBe("zh");
  });

  test.each(["fr-FR", "fr-CA"])("detects %s as French", (browserLang) => {
    const storage = { getItem: () => null };
    expect(detectLang(storage, [browserLang])).toBe("fr");
  });

  test("falls back to English for unsupported browser languages", () => {
    const storage = { getItem: () => null };
    expect(detectLang(storage, ["de-DE"])).toBe("en");
  });
});

describe("translations", () => {
  test("French missing keys fall back to English before Chinese", () => {
    const catalogs = {
      zh: { sample: "中文" },
      en: { sample: "English fallback" },
      fr: {},
    };
    expect(resolveMessage("fr", "sample", catalogs)).toBe("English fallback");
  });

  test("language metadata includes the French locale", () => {
    expect(LANGUAGES.fr.locale).toBe("fr-FR");
  });

  test("selector exposes all three supported languages", () => {
    const value = { lang: "fr", setLang: () => {}, t: (key) => key, locale: "fr-FR" };
    const tree = React.createElement(
      LanguageContext.Provider,
      { value },
      React.createElement(LanguageToggle)
    );
    const html = renderToStaticMarkup(tree);
    expect(html).toContain("中文");
    expect(html).toContain("English");
    expect(html).toContain("Français");
    expect(html).toContain('value="fr" selected=""');
  });

  test("French dictionary matches the complete English shape", () => {
    expect(shape(messages.fr)).toEqual(shape(messages.en));
  });
});
