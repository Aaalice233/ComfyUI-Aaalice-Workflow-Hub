const BASE = "/workflow-hub/api/v1";

// 多用户 ComfyUI 下宿主前端把当前用户存在 localStorage，请求必须透传该身份，
// 否则后端无法定位用户目录（Unknown user: default）。
function comfyUserHeader(): Record<string, string> {
  try {
    const user = window.localStorage.getItem("Comfy.userId");
    return user ? { "Comfy-User": user } : {};
  } catch {
    return {};
  }
}

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
  const comfyUser = comfyUserHeader();
  if (comfyUser["Comfy-User"] && !headers.has("Comfy-User")) headers.set("Comfy-User", comfyUser["Comfy-User"]);
  const method = (options.method || "GET").toUpperCase();
  const isWrite = method === "POST" || method === "PUT" || method === "PATCH" || method === "DELETE";
  if (isWrite && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const body = isWrite && options.body === undefined ? "{}" : options.body;
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    body,
    headers,
    credentials: "same-origin",
    cache: options.cache ?? "no-store",
  });
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
