import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

export const server = setupServer(
  http.get("/api/auth/me", () => HttpResponse.json({ detail: "unauthenticated" }, { status: 401 })),
);
export { http, HttpResponse };
