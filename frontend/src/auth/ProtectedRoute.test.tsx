import { it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { server, http, HttpResponse } from "../test/msw";
import { AuthProvider } from "./AuthContext";
import { ProtectedRoute } from "./ProtectedRoute";

function tree(initial: string) {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/login" element={<div>LOGIN</div>} />
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<div>HOME</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

it("нет user → редирект на /login", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json({ detail: "x" }, { status: 401 })));
  tree("/");
  await waitFor(() => expect(screen.getByText("LOGIN")).toBeInTheDocument());
});

it("есть user → рендерит защищённое", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "a", role: "user" })));
  tree("/");
  await waitFor(() => expect(screen.getByText("HOME")).toBeInTheDocument());
});
