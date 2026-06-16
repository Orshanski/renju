import { it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminPage from "./AdminPage";

vi.mock("./EngineTab", () => ({ EngineTab: () => <div>ENGINE TAB</div> }));
vi.mock("./UsersTab", () => ({ UsersTab: () => <div>USERS TAB</div> }));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: 1, username: "admin", role: "admin" }, loading: false, login: vi.fn(), logout: vi.fn() }),
}));

it("по умолчанию — вкладка Движок", async () => {
  render(<AdminPage />);
  expect(await screen.findByText("ENGINE TAB")).toBeInTheDocument();
});

it("вкладки переключаются — Пользователи рендерит UsersTab, Состояние — заглушка", async () => {
  render(<AdminPage />);
  await userEvent.click(screen.getByRole("button", { name: "Пользователи" }));
  expect(screen.getByText("USERS TAB")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Состояние" }));
  expect(screen.getByText(/в будущих релизах/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Движок" }));
  expect(screen.getByText("ENGINE TAB")).toBeInTheDocument();
});
