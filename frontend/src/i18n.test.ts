import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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

  it("interpolates dynamic values through the dictionary", () => {
    locale.value = "zh";
    expect(t.value("managerTasksQueued", { count: 3 })).toBe("已向 Manager 提交 3 个串行任务。");
    locale.value = "en";
    expect(t.value("managerTasksQueued", { count: 3 })).toBe("Queued 3 serial Manager tasks.");
  });

  it("keeps localized copy and locale branching out of application surfaces", () => {
    const appSource = readFileSync(resolve(process.cwd(), "src/App.vue"), "utf8");
    const hostSource = readFileSync(resolve(process.cwd(), "../web/comfyui/workflow_hub.js"), "utf8");
    const entryHtml = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const styleSource = readFileSync(resolve(process.cwd(), "src/style.css"), "utf8");
    expect(appSource).not.toMatch(/locale(?:\.value)?\s*===/);
    expect(appSource).not.toMatch(/\p{Script=Han}/u);
    expect(hostSource).not.toMatch(/\p{Script=Han}/u);
    expect(hostSource).not.toMatch(/\bisChinese\b|locale(?:\.value)?\s*===/);
    expect(hostSource).not.toMatch(/backdrop-filter/);
    expect(hostSource).toContain("revision: String(Date.now())");
    expect(entryHtml).not.toMatch(/\p{Script=Han}/u);
    expect(styleSource).not.toMatch(/font-size:\s*(?:[0-9]|1[01])px/);
  });
});
