import { describe, expect, it } from "vitest";
import { locale, resolveLocale, t } from "./i18n";

describe("translations", () => {
  it("contains the canonical name in both languages", () => {
    locale.value = "zh";
    expect(t.value("title")).toBe("工作流中心");
    locale.value = "en";
    expect(t.value("title")).toBe("Workflow Hub");
  });

  it("maps ComfyUI Chinese locales to Chinese and all other locales to English", () => {
    expect(resolveLocale("zh")).toBe("zh");
    expect(resolveLocale("zh-TW")).toBe("zh");
    expect(resolveLocale("en")).toBe("en");
    expect(resolveLocale("ja")).toBe("en");
  });
});
