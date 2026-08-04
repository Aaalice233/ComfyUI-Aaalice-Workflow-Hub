export const CATALOG_CACHE_FRESH_MS = 30_000;
export const CATALOG_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000;

const CACHE_VERSION = 1;
const CACHE_PREFIX = "aaalice-workflow-hub:catalog:";

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export type CatalogSnapshot<TSource, TProduct> = {
  sources: TSource[];
  products: TProduct[];
};

type StoredCatalogSnapshot<TSource, TProduct> = CatalogSnapshot<TSource, TProduct> & {
  version: number;
  saved_at: number;
};

export type CachedCatalog<TSource, TProduct> = CatalogSnapshot<TSource, TProduct> & {
  savedAt: number;
  fresh: boolean;
};

export class CatalogRequestCoordinator<T> {
  private inFlight: Promise<T> | null = null;
  private revision = 0;
  private appliedRevision = -1;

  constructor(private readonly fetcher: () => Promise<T>) {}

  invalidate() {
    this.revision += 1;
    this.appliedRevision = -1;
  }

  isCurrent() {
    return this.appliedRevision === this.revision;
  }

  get(): Promise<T> {
    const requestedRevision = this.revision;
    if (!this.inFlight) {
      const request = Promise.resolve().then(() => this.fetcher());
      this.inFlight = request;
      void request.then(
        () => {
          if (this.inFlight === request) {
            this.appliedRevision = requestedRevision;
            this.inFlight = null;
          }
        },
        () => {
          if (this.inFlight === request) this.inFlight = null;
        },
      );
    }
    const request = this.inFlight;
    return request.then((value) => {
      if (requestedRevision !== this.revision || this.appliedRevision < this.revision) return this.get();
      return value;
    });
  }
}

function browserStorage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function cacheKey(scope: string) {
  return `${CACHE_PREFIX}${scope}`;
}

export function readCatalogCache<TSource, TProduct>(
  scope: string,
  storage: StorageLike | undefined = browserStorage() || undefined,
  now = Date.now(),
): CachedCatalog<TSource, TProduct> | null {
  if (!scope || !storage) return null;
  try {
    const raw = storage.getItem(cacheKey(scope));
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<StoredCatalogSnapshot<TSource, TProduct>>;
    if (
      value.version !== CACHE_VERSION
      || !Number.isFinite(value.saved_at)
      || !Array.isArray(value.sources)
      || !Array.isArray(value.products)
    ) {
      storage.removeItem(cacheKey(scope));
      return null;
    }
    const age = Math.max(0, now - Number(value.saved_at));
    if (age > CATALOG_CACHE_MAX_AGE_MS) {
      storage.removeItem(cacheKey(scope));
      return null;
    }
    return {
      sources: value.sources,
      products: value.products,
      savedAt: Number(value.saved_at),
      fresh: age <= CATALOG_CACHE_FRESH_MS,
    };
  } catch {
    try {
      storage.removeItem(cacheKey(scope));
    } catch {
      // Storage can become unavailable between the read and cleanup.
    }
    return null;
  }
}

export function writeCatalogCache<TSource, TProduct>(
  scope: string,
  snapshot: CatalogSnapshot<TSource, TProduct>,
  storage: StorageLike | undefined = browserStorage() || undefined,
  now = Date.now(),
) {
  if (!scope || !storage) return;
  try {
    const value: StoredCatalogSnapshot<TSource, TProduct> = {
      version: CACHE_VERSION,
      saved_at: now,
      sources: snapshot.sources,
      products: snapshot.products,
    };
    storage.setItem(cacheKey(scope), JSON.stringify(value));
  } catch {
    // Catalog caching is an optimization and must not affect the live request.
  }
}

export function clearCatalogCache(scope: string, storage: StorageLike | undefined = browserStorage() || undefined) {
  if (!scope || !storage) return;
  try {
    storage.removeItem(cacheKey(scope));
  } catch {
    // Browser storage may be unavailable in hardened embedded views.
  }
}
