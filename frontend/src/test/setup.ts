import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./msw";
import { setUnauthorizedHandler } from "../api/client";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  setUnauthorizedHandler(() => {}); // сброс глобального 401-обработчика между тестами (изоляция между файлами)
});
afterAll(() => server.close());
