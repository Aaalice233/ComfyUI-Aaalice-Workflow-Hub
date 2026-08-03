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
    expect(t.value("dependenciesTargetExists", { path: "custom_nodes/example" })).toBe("目标目录 custom_nodes/example 已存在，未覆盖本地文件。");
    expect(t.value("pluginStatusMissing", { count: 2 })).toBe("缺少 2 个");
    expect(t.value("includedImagesDetail", { count: 1 })).toBe("包含 1 张随包图片，安装时会写入当前用户的隔离目录。");
    locale.value = "en";
    expect(t.value("dependenciesTargetExists", { path: "custom_nodes/example" })).toBe("The target directory custom_nodes/example already exists; local files were not overwritten.");
    expect(t.value("dependencyVersionTransition", { installed: "old", requested: "new" })).toBe("old → new");
    expect(t.value("pluginStatusMissing", { count: 2 })).toBe("2 missing");
    expect(t.value("includedImagesDetail", { count: 1 })).toBe("Includes 1 bundled image(s), installed into the current user's isolated directory.");
  });

  it("localizes publish and management stage progress in both languages", () => {
    locale.value = "zh";
    expect(t.value("publishStageProgress", { current: 5, total: 5, stage: t.value("stageUpdatingRepository") })).toBe("发布阶段 5/5 · 正在写入仓库");
    expect(t.value("operationStageProgress", { current: 2, total: 3, stage: t.value("stageDeletingRelease") })).toBe("操作阶段 2/3 · 正在删除 Release");
    locale.value = "en";
    expect(t.value("publishStageProgress", { current: 5, total: 5, stage: t.value("stageUpdatingRepository") })).toBe("Publish stage 5 of 5 · Updating repository");
    expect(t.value("operationStageProgress", { current: 2, total: 3, stage: t.value("stageDeletingRelease") })).toBe("Operation stage 2 of 3 · Deleting Release");
  });

  it("interpolates core version alignment details in both languages", () => {
    locale.value = "zh";
    expect(t.value("coreVersionAlignedDetail", { current: "0.28.0", required: "ComfyUI 0.28.0" })).toBe("当前 ComfyUI 0.28.0 满足工作流要求 ComfyUI 0.28.0。");
    locale.value = "en";
    expect(t.value("coreVersionAlignedDetail", { current: "0.28.0", required: "ComfyUI 0.28.0" })).toBe("ComfyUI 0.28.0 satisfies the workflow requirement ComfyUI 0.28.0.");
  });

  it("interpolates download preflight copy in both languages", () => {
    locale.value = "zh";
    expect(t.value("downloadCheckDescription", { name: "Demo", version: "1.2.0" })).toBe("下载 Demo v1.2.0 前，先检查 ComfyUI 内核和插件依赖，避免下载后无法运行。");
    locale.value = "en";
    expect(t.value("downloadCheckDescription", { name: "Demo", version: "1.2.0" })).toBe("Before downloading Demo v1.2.0, we will check the ComfyUI core and plugin dependencies to avoid an unusable workflow.");
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
