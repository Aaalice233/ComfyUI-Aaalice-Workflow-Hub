import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { locale, messages, resolveLocale, setLocale, t, type MessageKey } from "./i18n";

describe("translations", () => {
  it("contains the canonical name in all three languages", () => {
    locale.value = "zh";
    expect(t.value("title")).toBe("工作流中心");
    locale.value = "zh-TW";
    expect(t.value("title")).toBe("工作流程中心");
    locale.value = "en";
    expect(t.value("title")).toBe("Workflow Hub");
  });

  it("maps ComfyUI and browser locale variants to the supported locales", () => {
    expect(resolveLocale("zh")).toBe("zh");
    expect(resolveLocale("zh-CN")).toBe("zh");
    expect(resolveLocale("zh-Hans")).toBe("zh");
    expect(resolveLocale("zh_TW")).toBe("zh-TW");
    expect(resolveLocale("zh-Hant")).toBe("zh-TW");
    expect(resolveLocale("zh-HK")).toBe("zh-TW");
    expect(resolveLocale("ZH_mo")).toBe("zh-TW");
    expect(resolveLocale("en")).toBe("en");
    expect(resolveLocale("ja")).toBe("en");
  });

  it("sets the matching HTML language", () => {
    setLocale("zh-Hans");
    expect(document.documentElement.lang).toBe("zh-CN");
    setLocale("zh-Hant");
    expect(document.documentElement.lang).toBe("zh-TW");
    setLocale("en-US");
    expect(document.documentElement.lang).toBe("en");
  });

  it("keeps every dictionary complete with matching placeholders", () => {
    const keys = Object.keys(messages.zh) as MessageKey[];
    const placeholders = (message: string) => [...message.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();

    expect(Object.keys(messages["zh-TW"]).sort()).toEqual([...keys].sort());
    expect(Object.keys(messages.en).sort()).toEqual([...keys].sort());
    for (const key of keys) {
      expect(placeholders(messages["zh-TW"][key]), key).toEqual(placeholders(messages.zh[key]));
      expect(placeholders(messages.en[key]), key).toEqual(placeholders(messages.zh[key]));
    }
  });

  it("interpolates dynamic values through the dictionary", () => {
    locale.value = "zh";
    expect(t.value("dependenciesTargetExists", { path: "custom_nodes/example" })).toBe("目标目录 custom_nodes/example 已存在，未覆盖本地文件。");
    expect(t.value("dependenciesNonGitInstall")).toBe("检测到同名非 Git 安装，需要手动移除。");
    expect(t.value("nonGitInstall")).toBe("非 Git 安装");
    expect(t.value("pluginStatusMissing", { count: 2 })).toBe("缺少 2 个");
    expect(t.value("includedImagesDetail", { count: 1 })).toBe("包含 1 张随包图片，安装时会写入 ComfyUI 的 input 目录，工作流引用保持不变。");
    expect(t.value("downloadComplete", { name: "Demo", version: "1.2.0" })).toBe("工作流 Demo v1.2.0 已下载完成。");
    expect(t.value("workflowLoadFailed", { detail: "文件不存在" })).toBe("工作流加载失败：文件不存在");
    expect(t.value("workflowLoadMissingFromStorage", { path: "workflows/Demo.json" })).toBe("ComfyUI 未在工作流目录中找到 workflows/Demo.json，请重新下载后重试。");
    expect(t.value("clearCompletedActivities", { count: 2 })).toBe("清除已完成（2）");
    expect(t.value("activityTime", { time: "2026/01/01 12:00:00" })).toBe("时间：2026/01/01 12:00:00");
    expect(t.value("publishCompleteDescription", { name: "Demo", version: "1.2.0" })).toBe("Demo v1.2.0 已成功发布，并已写入工作流目录。");
    locale.value = "zh-TW";
    expect(t.value("dependenciesTargetExists", { path: "custom_nodes/example" })).toBe("目標資料夾 custom_nodes/example 已存在，未覆寫本機檔案。");
    expect(t.value("dependenciesNonGitInstall")).toBe("偵測到同名非 Git 安裝，需要手動移除。");
    expect(t.value("nonGitInstall")).toBe("非 Git 安裝");
    expect(t.value("pluginStatusMissing", { count: 2 })).toBe("缺少 2 個");
    expect(t.value("includedImagesDetail", { count: 1 })).toBe("包含 1 張隨附圖片，安裝時會寫入 ComfyUI 的 input 資料夾，工作流程參照保持不變。");
    expect(t.value("downloadComplete", { name: "Demo", version: "1.2.0" })).toBe("工作流程 Demo v1.2.0 已下載完成。");
    expect(t.value("workflowLoadFailed", { detail: "檔案不存在" })).toBe("工作流程載入失敗：檔案不存在");
    expect(t.value("workflowLoadMissingFromStorage", { path: "workflows/Demo.json" })).toBe("ComfyUI 未在工作流程資料夾中找到 workflows/Demo.json，請重新下載後重試。");
    expect(t.value("clearCompletedActivities", { count: 2 })).toBe("清除已完成（2）");
    expect(t.value("activityTime", { time: "2026/01/01 12:00:00" })).toBe("時間：2026/01/01 12:00:00");
    expect(t.value("publishCompleteDescription", { name: "Demo", version: "1.2.0" })).toBe("Demo v1.2.0 已成功發佈，並已寫入工作流程目錄。");
    locale.value = "en";
    expect(t.value("dependenciesTargetExists", { path: "custom_nodes/example" })).toBe("The target directory custom_nodes/example already exists; local files were not overwritten.");
    expect(t.value("dependenciesNonGitInstall")).toBe("A non-Git installation with the same name was found. Remove it manually first.");
    expect(t.value("nonGitInstall")).toBe("Non-Git installation");
    expect(t.value("dependencyVersionTransition", { installed: "old", requested: "new" })).toBe("old → new");
    expect(t.value("pluginStatusMissing", { count: 2 })).toBe("2 missing");
    expect(t.value("includedImagesDetail", { count: 1 })).toBe("Includes 1 bundled image(s), installed into ComfyUI's input directory with workflow references unchanged.");
    expect(t.value("downloadComplete", { name: "Demo", version: "1.2.0" })).toBe("Demo v1.2.0 finished downloading.");
    expect(t.value("workflowLoadFailed", { detail: "File not found" })).toBe("Failed to load the workflow: File not found");
    expect(t.value("workflowLoadMissingFromStorage", { path: "workflows/Demo.json" })).toBe("ComfyUI could not find workflows/Demo.json in workflow storage. Download it again and retry.");
    expect(t.value("clearCompletedActivities", { count: 2 })).toBe("Clear completed (2)");
    expect(t.value("activityTime", { time: "01/01/2026 12:00:00" })).toBe("Time: 01/01/2026 12:00:00");
    expect(t.value("publishCompleteDescription", { name: "Demo", version: "1.2.0" })).toBe("Demo v1.2.0 was published and added to the workflow catalog.");
  });

  it("localizes publish and management stage progress in all three languages", () => {
    locale.value = "zh";
    expect(t.value("publishStageProgress", { current: 5, total: 5, stage: t.value("stageUpdatingRepository") })).toBe("发布阶段 5/5 · 正在写入仓库");
    expect(t.value("operationStageProgress", { current: 2, total: 3, stage: t.value("stageDeletingRelease") })).toBe("操作阶段 2/3 · 正在删除 Release");
    locale.value = "zh-TW";
    expect(t.value("publishStageProgress", { current: 5, total: 5, stage: t.value("stageUpdatingRepository") })).toBe("發佈階段 5/5 · 正在寫入儲存庫");
    expect(t.value("operationStageProgress", { current: 2, total: 3, stage: t.value("stageDeletingRelease") })).toBe("操作階段 2/3 · 正在刪除 Release");
    locale.value = "en";
    expect(t.value("publishStageProgress", { current: 5, total: 5, stage: t.value("stageUpdatingRepository") })).toBe("Publish stage 5 of 5 · Updating repository");
    expect(t.value("operationStageProgress", { current: 2, total: 3, stage: t.value("stageDeletingRelease") })).toBe("Operation stage 2 of 3 · Deleting Release");
  });

  it("interpolates core version alignment details in all three languages", () => {
    locale.value = "zh";
    expect(t.value("coreVersionAlignedDetail", { current: "0.28.0", required: "ComfyUI 0.28.0" })).toBe("当前 ComfyUI 0.28.0 满足工作流要求 ComfyUI 0.28.0。");
    locale.value = "zh-TW";
    expect(t.value("coreVersionAlignedDetail", { current: "0.28.0", required: "ComfyUI 0.28.0" })).toBe("目前 ComfyUI 0.28.0 滿足工作流程需求 ComfyUI 0.28.0。");
    locale.value = "en";
    expect(t.value("coreVersionAlignedDetail", { current: "0.28.0", required: "ComfyUI 0.28.0" })).toBe("ComfyUI 0.28.0 satisfies the workflow requirement ComfyUI 0.28.0.");
  });

  it("interpolates download preflight copy in all three languages", () => {
    locale.value = "zh";
    expect(t.value("downloadCheckDescription", { name: "Demo", version: "1.2.0" })).toBe("下载 Demo v1.2.0 前，先检查 ComfyUI 内核和插件依赖，避免下载后无法运行。");
    locale.value = "zh-TW";
    expect(t.value("downloadCheckDescription", { name: "Demo", version: "1.2.0" })).toBe("下載 Demo v1.2.0 前，先檢查 ComfyUI 核心和外掛相依性，避免下載後無法執行。");
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
