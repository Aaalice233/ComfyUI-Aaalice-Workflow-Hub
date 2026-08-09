import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const appSource = readFileSync(resolve(process.cwd(), "src/App.vue"), "utf8");
const styleSource = readFileSync(resolve(process.cwd(), "src/style.css"), "utf8");

function rule(selector: string) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = styleSource.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  expect(match, `Missing CSS rule for ${selector}`).not.toBeNull();
  return match?.[1] || "";
}

describe("workflow detail scrolling layout", () => {
  it("keeps the version list and release content as the only independent scroll regions", () => {
    expect(appSource).toContain('ref="detailReleaseScroll" class="detail-release-scroll"');
    expect(rule(".detail")).toContain("overflow: hidden");
    expect(rule(".detail-workbench")).toContain("overflow: hidden");
    expect(rule(".version-rail")).toContain("overflow-y: auto");
    expect(rule(".detail-release-scroll")).toContain("overflow-y: auto");
  });

  it("lets changelog content flow through the release scrollbar", () => {
    const changelogRule = rule(".changelog");
    expect(changelogRule).not.toMatch(/max-height|overflow-y|scrollbar-/);
    expect(appSource).toContain('detailReleaseScroll.value?.scrollTo({ top: 0, behavior: "smooth" })');
  });
});
