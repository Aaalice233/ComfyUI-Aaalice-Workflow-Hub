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
    expect(options.cache).toBe("no-store");
    expect(options.headers.get("Content-Type")).toBe("application/json");
  });

  it("preserves backend error codes and interpolation parameters", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      statusText: "Bad Request",
      json: async () => ({ error_code: "publisher.lora_forbidden", error_params: { count: 2 } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api("/publisher/validate", { method: "POST" })).rejects.toMatchObject({
      code: "publisher.lora_forbidden",
      params: { count: 2 },
    });
  });
});
