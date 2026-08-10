import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const appSource = readFileSync(resolve(process.cwd(), "src/App.vue"), "utf8");

describe("dependency operation coordination", () => {
  it("blocks another submission while a dependency operation is pending or running", () => {
    expect(appSource).toContain("return !operation || isOperationActive(operation)");
    expect(appSource).toContain("if (!item || !version || dependencyOperationRunning.value) return");
    expect(appSource).toContain("downloadPreflight.syncing || dependencyOperationRunning");
  });

  it("rechecks dependency state before an automatic post-sync download", () => {
    const terminalWatch = appSource.slice(
      appSource.indexOf("watch(operations, async (items) =>"),
      appSource.indexOf("function dependencyWarning", appSource.indexOf("watch(operations, async (items) =>")),
    );
    expect(terminalWatch).toContain("await refreshDownloadPreflightDependencies(check)");
    expect(terminalWatch).toContain("dependencies.some((entry) => entry.action !== \"keep\")");
    expect(terminalWatch.indexOf("await refreshDownloadPreflightDependencies(check)"))
      .toBeLessThan(terminalWatch.indexOf("void download(check.item, check.version)"));
  });

  it("surfaces every backup created for local commits and working-tree changes", () => {
    expect(appSource).toContain("entry.backup_refs?.length ? entry.backup_refs");
    expect(appSource).toContain('t.value("dependencyBackupCreated", { refs: refs.join(", ") })');
    expect(appSource).toContain("dependencyBackupMessage(task)");
  });
});
