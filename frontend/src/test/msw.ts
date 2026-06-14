import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

export const server = setupServer(
  http.get("/api/auth/me", () => HttpResponse.json({ detail: "unauthenticated" }, { status: 401 })),
  // дефолт-справочник уровней (HomePage тянет его для имён уровней-pill); тесты переопределяют по нужде
  http.get("/api/levels", () => HttpResponse.json([])),
);
export { http, HttpResponse };
