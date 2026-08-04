import { describe, expect, it, vi } from "vitest";
import {
  CATALOG_CACHE_FRESH_MS,
  CATALOG_CACHE_MAX_AGE_MS,
  CatalogRequestCoordinator,
  clearCatalogCache,
  readCatalogCache,
  writeCatalogCache,
} from "./catalog-cache";

class MemoryStorage {
  private values = new Map<string, string>();

  getItem(key: string) {
    return this.values.get(key) || null;
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }

  removeItem(key: string) {
    this.values.delete(key);
  }
}

describe("catalog cache", () => {
  it("deduplicates concurrent catalog requests", async () => {
    const fetcher = vi.fn(async () => "catalog");
    const coordinator = new CatalogRequestCoordinator(fetcher);

    await expect(Promise.all([coordinator.get(), coordinator.get()])).resolves.toEqual(["catalog", "catalog"]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("does not let an invalidated request overwrite newer data", async () => {
    let releaseFirst!: (value: string) => void;
    const firstRequest = new Promise<string>((resolve) => { releaseFirst = resolve; });
    const fetcher = vi.fn()
      .mockImplementationOnce(() => firstRequest)
      .mockImplementationOnce(async () => "new catalog");
    const coordinator = new CatalogRequestCoordinator(fetcher);
    const first = coordinator.get();
    await Promise.resolve();
    coordinator.invalidate();
    const second = coordinator.get();
    releaseFirst("old catalog");

    await expect(Promise.all([first, second])).resolves.toEqual(["new catalog", "new catalog"]);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("round-trips a fresh catalog snapshot", () => {
    const storage = new MemoryStorage();
    const now = 100_000;
    const snapshot = { sources: [{ owner: "owner" }], products: [{ id: "workflow" }] };

    writeCatalogCache("user-a", snapshot, storage, now);

    expect(readCatalogCache("user-a", storage, now + CATALOG_CACHE_FRESH_MS)).toEqual({
      ...snapshot,
      savedAt: now,
      fresh: true,
    });
  });

  it("keeps stale data available for stale-while-revalidate", () => {
    const storage = new MemoryStorage();
    const now = 100_000;
    const snapshot = { sources: [], products: [{ id: "workflow" }] };

    writeCatalogCache("user-a", snapshot, storage, now);

    expect(readCatalogCache("user-a", storage, now + CATALOG_CACHE_FRESH_MS + 1)?.fresh).toBe(false);
    expect(readCatalogCache("user-a", storage, now + CATALOG_CACHE_FRESH_MS + 1)?.products).toEqual(snapshot.products);
  });

  it("discards expired or malformed entries without affecting other scopes", () => {
    const storage = new MemoryStorage();
    const now = 100_000;
    writeCatalogCache("user-a", { sources: [], products: [] }, storage, now);
    storage.setItem("aaalice-workflow-hub:catalog:user-b", "not-json");

    expect(readCatalogCache("user-a", storage, now + CATALOG_CACHE_MAX_AGE_MS + 1)).toBeNull();
    expect(readCatalogCache("user-b", storage, now)).toBeNull();

    writeCatalogCache("user-a", { sources: [{ owner: "owner" }], products: [] }, storage, now);
    clearCatalogCache("user-a", storage);
    expect(readCatalogCache("user-a", storage, now)).toBeNull();
  });
});
