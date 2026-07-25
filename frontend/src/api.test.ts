import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api", () => {
  it("sends empty write requests as JSON objects", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    });
    vi.stubGlobal("fetch", fetchMock);

    await api("/empty-write", { method: "POST" });

    const [, options] = fetchMock.mock.calls[0];
    expect(options.body).toBe("{}");
    expect(options.headers.get("Content-Type")).toBe("application/json");
  });
});
