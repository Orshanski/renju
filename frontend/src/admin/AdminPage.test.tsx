import { it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminPage from "./AdminPage";

vi.mock("./EngineTab", () => ({ EngineTab: () => <div>ENGINE TAB</div> }));

it("по умолчанию — вкладка Движок", async () => {
  render(<AdminPage />);
  expect(await screen.findByText("ENGINE TAB")).toBeInTheDocument();
});

it("вкладки переключаются, Пользователи/Состояние — заглушки", async () => {
  render(<AdminPage />);
  await userEvent.click(screen.getByRole("button", { name: "Пользователи" }));
  expect(screen.getByText(/в будущих релизах/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Состояние" }));
  expect(screen.getByText(/в будущих релизах/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Движок" }));
  expect(screen.getByText("ENGINE TAB")).toBeInTheDocument();
});
