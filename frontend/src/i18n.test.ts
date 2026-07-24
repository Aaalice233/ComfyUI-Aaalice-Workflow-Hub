import { describe, expect, it } from "vitest";
import { locale, t } from "./i18n";

describe("translations", () => {
  it("contains the canonical name in both languages", () => {
    locale.value = "zh";
    expect(t.value("title")).toBe("工作流中心");
    locale.value = "en";
    expect(t.value("title")).toBe("Workflow Hub");
  });
});
