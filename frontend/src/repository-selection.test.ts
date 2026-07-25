import { describe, expect, it } from "vitest";
import { resolvePublishRepositoryUrl, type PublishRepository } from "./repository-selection";

const repositories: PublishRepository[] = [
  { full_name: "Aaalice233/Aaalice-Workflows" },
  { full_name: "Aaalice233/Other-Workflows" },
];

describe("resolvePublishRepositoryUrl", () => {
  it("keeps the current repository when it is still available", () => {
    expect(resolvePublishRepositoryUrl(
      repositories,
      "https://github.com/Aaalice233/Other-Workflows",
      "https://github.com/Aaalice233/Aaalice-Workflows"
    )).toBe("https://github.com/Aaalice233/Other-Workflows");
  });

  it("restores the remembered repository on first entry", () => {
    expect(resolvePublishRepositoryUrl(
      repositories,
      "",
      "https://github.com/aaalice233/other-workflows/"
    )).toBe("https://github.com/Aaalice233/Other-Workflows");
  });

  it("selects the first available repository when no saved choice is valid", () => {
    expect(resolvePublishRepositoryUrl(
      repositories,
      "https://github.com/Aaalice233/Renamed-Repository",
      "https://github.com/Aaalice233/Deleted-Repository"
    )).toBe("https://github.com/Aaalice233/Aaalice-Workflows");
  });

  it("returns an empty value when no repository is available", () => {
    expect(resolvePublishRepositoryUrl([], "", "")).toBe("");
  });
});
