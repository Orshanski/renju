import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { server } from "./msw";
import { setUnauthorizedHandler } from "../api/client";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  setUnauthorizedHandler(() => {}); // сброс глобального 401-обработчика между тестами (изоляция между файлами)
  vi.unstubAllGlobals(); // стаб EventSource не утекает между тестами (ревью плана, M3)
});
afterAll(() => server.close());
