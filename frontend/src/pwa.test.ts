import { it, expect, vi } from "vitest";

const registerSW = vi.fn();
vi.mock("virtual:pwa-register", () => ({ registerSW }));

it("registerPwa вызывает registerSW immediate", async () => {
  const { registerPwa } = await import("./pwa");
  registerPwa();
  expect(registerSW).toHaveBeenCalledWith({ immediate: true });
});
