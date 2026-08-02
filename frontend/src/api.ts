const BASE = "/workflow-hub/api/v1";

type ApiErrorParams = Record<string, string | number>;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly params?: ApiErrorParams,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const method = (options.method || "GET").toUpperCase();
  const isWrite = method === "POST" || method === "PUT" || method === "PATCH" || method === "DELETE";
  if (isWrite && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const body = isWrite && options.body === undefined ? "{}" : options.body;
  const response = await fetch(`${BASE}${path}`, { ...options, body, headers, credentials: "same-origin" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(
      data.error || data.error_code || `${response.status} ${response.statusText}`,
      response.status,
      data.error_code,
      data.error_params,
    );
  }
  return data as T;
}

export const post = <T>(path: string, data: unknown) =>
  api<T>(path, { method: "POST", body: JSON.stringify(data) });

export const remove = <T>(path: string, data: unknown = {}) =>
  api<T>(path, { method: "DELETE", body: JSON.stringify(data) });
