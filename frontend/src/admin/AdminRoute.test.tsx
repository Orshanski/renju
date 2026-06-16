import { it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AdminRoute } from "./AdminRoute";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockAuth,
}));
let mockAuth: { user: { role: string } | null; loading: boolean };

function renderAt() {
  return render(
    <MemoryRouter initialEntries={["/admin"]}>
      <Routes>
        <Route element={<AdminRoute />}>
          <Route path="/admin" element={<div>ADMIN OK</div>} />
        </Route>
        <Route path="/" element={<div>HOME</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

it("admin → пускает", async () => {
  mockAuth = { user: { role: "admin" }, loading: false };
  renderAt();
  expect(await screen.findByText("ADMIN OK")).toBeInTheDocument();
});

it("user → редирект на /", async () => {
  mockAuth = { user: { role: "user" }, loading: false };
  renderAt();
  expect(await screen.findByText("HOME")).toBeInTheDocument();
});
