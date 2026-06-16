import { it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import SettingsPage from "./SettingsPage";

it("рендерит заголовок и «в будущих релизах»", () => {
  render(<SettingsPage />);
  expect(screen.getByRole("heading", { name: /Настройки/i })).toBeInTheDocument();
  expect(screen.getByText(/в будущих релизах/i)).toBeInTheDocument();
});
