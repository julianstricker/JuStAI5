// Minimal typed fetch wrapper for the JuStAI5 REST API.
// Auth uses an httpOnly session cookie; state-changing requests carry the
// x-justai header (CSRF protection, see backend api/deps.py).

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

async function request<T>(method: Method, path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "x-justai": "1" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["content-type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload, credentials: "same-origin", ...init });
  if (!res.ok) {
    let data: { error?: string; message?: string; details?: unknown; detail?: unknown } = {};
    try {
      data = await res.json();
    } catch {
      /* not JSON */
    }
    const message =
      data.message ?? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? res.statusText));
    throw new ApiError(res.status, data.error ?? String(res.status), message, data.details ?? data.detail);
  }
  const type = res.headers.get("content-type") ?? "";
  if (type.includes("application/json")) return (await res.json()) as T;
  return (await res.blob()) as unknown as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body ?? {}),
  del: <T>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, form),
};

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}
