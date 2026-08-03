import { describe, expect, it } from "vitest";
import { renderMarkdown } from "./markdown";

describe("renderMarkdown", () => {
  it("renders GFM headings, lists, tables, and fenced code", () => {
    const html = renderMarkdown("## Changes\n\n- one\n- two\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n```ts\nconst value = 1;\n```");

    expect(html).toContain("<h2>Changes</h2>");
    expect(html).toContain("<ul>");
    expect(html).toContain("<table>");
    expect(html).toContain("const value = 1;");
  });

  it("sanitizes executable HTML and unsafe links", () => {
    const html = renderMarkdown("<script>alert(1)</script>\n\n<a href=\"javascript:alert(1)\">unsafe</a>");

    expect(html).not.toContain("<script");
    expect(html).not.toContain("javascript:");
    expect(html).toContain("unsafe");
  });
});
