import { expect, test } from "@playwright/test";

test("opens the independent workflow hub page", async ({ page }) => {
  await page.goto("/workflow-hub");
  await expect(page.getByRole("strong", { name: "工作流中心" })).toBeVisible();
  await expect(page.getByRole("button", { name: "订阅工作流" })).toBeVisible();
  await expect(page.getByRole("button", { name: "发布工作流" })).toBeVisible();
});
