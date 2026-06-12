import { describe, it, expect, vi } from "vitest";
import { server, http, HttpResponse } from "../test/msw";
import { apiRequest, ApiError, setUnauthorizedHandler } from "./client";

describe("apiRequest", () => {
  it("GET парсит JSON, без CSRF-заголовка", async () => {
    let xrw: string | null = "init";
    server.use(http.get("/api/ping", ({ request }) => {
      xrw = request.headers.get("X-Requested-With");
      return HttpResponse.json({ pong: true });
    }));
    const data = await apiRequest<{ pong: boolean }>("GET", "/api/ping");
    expect(data).toEqual({ pong: true });
    expect(xrw).toBeNull(); // GET — безопасный, CSRF-заголовок не нужен
  });

  it("POST шлёт X-Requested-With (CSRF)", async () => {
    let xrw: string | null = null;
    let ct: string | null = null;
    server.use(http.post("/api/thing", ({ request }) => {
      xrw = request.headers.get("X-Requested-With");
      ct = request.headers.get("Content-Type");
      return HttpResponse.json({ ok: true });
    }));
    await apiRequest("POST", "/api/thing", { a: 1 });
    expect(xrw).toBe("XMLHttpRequest");
    expect(ct).toBe("application/json");
    // credentials:"include" НЕ проверяем юнитом: msw/Node не форвардит fetch-init
    // credentials в request.credentials (всегда "same-origin"). Реальную отправку куки
    // покрывает живой смоук (Task 8).
  });

  it("на не-2xx кидает ApiError со status и detail", async () => {
    server.use(http.post("/api/bad", () => HttpResponse.json({ detail: "nope" }, { status: 422 })));
    await expect(apiRequest("POST", "/api/bad")).rejects.toMatchObject({ status: 422, detail: "nope" });
    await expect(apiRequest("POST", "/api/bad")).rejects.toBeInstanceOf(ApiError);
  });

  it("401 дёргает глобальный обработчик; с opts.skipAuthRedirect — НЕ дёргает", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    server.use(http.get("/api/secure", () => HttpResponse.json({ detail: "x" }, { status: 401 })));
    await expect(apiRequest("GET", "/api/secure")).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);

    onUnauthorized.mockClear();
    server.use(http.post("/api/login-like", () => HttpResponse.json({ detail: "x" }, { status: 401 })));
    await expect(apiRequest("POST", "/api/login-like", {}, { skipAuthRedirect: true })).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("не-JSON тело ошибки → detail = statusText (fallback)", async () => {
    server.use(http.get("/api/text-error", () =>
      new HttpResponse("oops", { status: 500, statusText: "Internal Server Error" })));
    await expect(apiRequest("GET", "/api/text-error")).rejects.toMatchObject({
      status: 500,
      detail: "Internal Server Error",
    });
  });

  it("204 → resolves undefined (без парсинга тела)", async () => {
    server.use(http.delete("/api/gone", () => new HttpResponse(null, { status: 204 })));
    await expect(apiRequest("DELETE", "/api/gone")).resolves.toBeUndefined();
  });
});
