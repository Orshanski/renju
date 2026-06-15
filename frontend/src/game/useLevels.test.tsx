import { renderHook, waitFor } from "@testing-library/react";
import { server, http, HttpResponse } from "../test/msw";
import { useLevels } from "./useLevels";

it("resolves level id to name after load", async () => {
  server.use(http.get("/api/levels", () => HttpResponse.json([{ id: "master", name: "Мастер" }])));
  const { result } = renderHook(() => useLevels());
  await waitFor(() => expect(result.current.nameOf("master")).toBe("Мастер"));
});

it("returns undefined for unknown / nullish id", () => {
  const { result } = renderHook(() => useLevels());
  expect(result.current.nameOf(undefined)).toBeUndefined();
});
