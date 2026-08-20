import { describe, expect, it } from "vitest";

import { resolveHostLocale, translateHost } from "../../web/comfyui/i18n.js";

describe("host translations", () => {
  it("maps Simplified and Traditional Chinese locale variants independently", () => {
    expect(resolveHostLocale("zh-CN")).toBe("zh");
    expect(resolveHostLocale("zh-Hans")).toBe("zh");
    expect(resolveHostLocale("zh_TW")).toBe("zh-TW");
    expect(resolveHostLocale("zh-Hant")).toBe("zh-TW");
    expect(resolveHostLocale("zh-HK")).toBe("zh-TW");
    expect(resolveHostLocale("en-US")).toBe("en");
  });

  it("renders Traditional Chinese host notifications with interpolation", () => {
    expect(translateHost("zh-TW", "tooltip")).toBe("開啟工作流程中心（Shift+點擊可在新視窗開啟）");
    expect(translateHost("zh-TW", "updatesAvailable", { count: 3 })).toBe("工作流程中心有 3 個新版本");
    expect(translateHost("zh-TW", "ignoreUpdate", { name: "Demo", version: "1.2.0" })).toBe("忽略 Demo v1.2.0");
  });
});
