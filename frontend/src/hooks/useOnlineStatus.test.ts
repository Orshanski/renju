// frontend/src/hooks/useOnlineStatus.test.ts
import { renderHook, act } from "@testing-library/react";
import { it, expect, vi, afterEach } from "vitest";
import { useOnlineStatus } from "./useOnlineStatus";

// общий setup.ts не делает restoreAllMocks → снимаем spy на navigator.onLine сами,
// чтобы мок не протёк в другие файлы
afterEach(() => vi.restoreAllMocks());

it("стартует со значением navigator.onLine", () => {
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  const { result } = renderHook(() => useOnlineStatus());
  expect(result.current).toBe(true);
});

it("offline-событие → false, online-событие → true", () => {
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  const { result } = renderHook(() => useOnlineStatus());
  act(() => { window.dispatchEvent(new Event("offline")); });
  expect(result.current).toBe(false);
  act(() => { window.dispatchEvent(new Event("online")); });
  expect(result.current).toBe(true);
});
