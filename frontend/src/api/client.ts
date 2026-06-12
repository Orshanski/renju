export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}

type Options = { skipAuthRedirect?: boolean };

let unauthorizedHandler: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  unauthorizedHandler = fn;
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

export async function apiRequest<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
  opts: Options = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (!SAFE.has(method)) headers["X-Requested-With"] = "XMLHttpRequest"; // CSRF (csrf.py)
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const resp = await fetch(path, {
    method,
    credentials: "include", // httpOnly-кука
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (resp.status === 401 && !opts.skipAuthRedirect) unauthorizedHandler();

  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const j = await resp.json();
      if (j && typeof j.detail === "string") detail = j.detail;
    } catch { /* тело не JSON — оставляем statusText */ }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
