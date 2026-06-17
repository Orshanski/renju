// frontend/src/pages/SettingsPage.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, it, expect, beforeEach } from "vitest";

// vi.mock поднимается до импортов — мокаем до загрузки компонента (паттерн UsersTab.test.tsx)
vi.mock("../settings.api", () => ({
  getSettings: vi.fn(),
  saveSettings: vi.fn(),
  changePassword: vi.fn(),
}));

vi.mock("../game/api", () => ({
  bulkDeleteGames: vi.fn(),
}));

import SettingsPage from "./SettingsPage";
import * as settingsApi from "../settings.api";
import * as gameApi from "../game/api";

const defaultSettings = {
  games_limit: 50,
  games_limit_enabled: true,
  undo_enabled: true,
  undo_limit: null,
  undo_after_game_end: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(settingsApi.getSettings).mockResolvedValue({ ...defaultSettings });
  vi.mocked(settingsApi.saveSettings).mockResolvedValue({ ...defaultSettings });
  vi.mocked(settingsApi.changePassword).mockResolvedValue(undefined);
  vi.mocked(gameApi.bulkDeleteGames).mockResolvedValue(undefined);
});

it("отображает заголовок Настройки", async () => {
  render(<SettingsPage />);
  expect(await screen.findByRole("heading", { name: /Настройки/i })).toBeInTheDocument();
});

it("кнопка Сохранить disabled пока нет изменений", async () => {
  render(<SettingsPage />);
  const btn = await screen.findByRole("button", { name: /Сохранить/i });
  expect(btn).toBeDisabled();
});

it("кнопка Сохранить активируется при изменении toggle", async () => {
  render(<SettingsPage />);
  await screen.findByRole("heading", { name: /Настройки/i });
  const toggle = screen.getAllByRole("switch")[0]; // undo toggle
  fireEvent.click(toggle);
  const btn = screen.getByRole("button", { name: /Сохранить/i });
  expect(btn).not.toBeDisabled();
});

it("диалог удаления открывается при клике на Удалить все", async () => {
  render(<SettingsPage />);
  await screen.findByRole("heading", { name: /Настройки/i });
  const deleteBtn = screen.getAllByText("Удалить все")[0];
  fireEvent.click(deleteBtn);
  expect(screen.getByText(/Это действие нельзя отменить/i)).toBeInTheDocument();
});

it("подтверждение удаления вызывает bulkDeleteGames", async () => {
  render(<SettingsPage />);
  await screen.findByRole("heading", { name: /Настройки/i });
  // Открыть диалог первой кнопкой «Удалить все»
  fireEvent.click(screen.getAllByText("Удалить все")[0]);
  // В модале появляется кнопка-подтверждение — берём последнюю (в оверлее), не строчную
  const confirmBtns = screen.getAllByRole("button", { name: /Удалить все/i });
  fireEvent.click(confirmBtns[confirmBtns.length - 1]);
  await waitFor(() => expect(gameApi.bulkDeleteGames).toHaveBeenCalledWith("current"));
});

it("ошибка 400 при смене пароля показывает errMsg", async () => {
  vi.spyOn(settingsApi, "changePassword").mockRejectedValue(new Error("Неверный текущий пароль"));
  render(<SettingsPage />);
  await screen.findByRole("heading", { name: /Настройки/i });
  fireEvent.change(screen.getByLabelText(/Текущий пароль/i), { target: { value: "wrong" } });
  fireEvent.change(screen.getByLabelText(/Новый пароль/i), { target: { value: "newpass123" } });
  fireEvent.click(screen.getByRole("button", { name: /Обновить пароль/i }));
  expect(await screen.findByText("Неверный текущий пароль")).toBeInTheDocument();
});

it("показывает предупреждение про другие устройства", async () => {
  render(<SettingsPage />);
  await screen.findByText(/другие устройства/i);
});

it("включение лимита (был выключен) требует подтверждения перед сохранением", async () => {
  vi.mocked(settingsApi.getSettings).mockResolvedValue({
    ...defaultSettings,
    games_limit_enabled: false,
    undo_enabled: false,
  });
  render(<SettingsPage />);
  await screen.findByRole("heading", { name: /Настройки/i });
  // switch'и при undo off: [undo_enabled, games_limit_enabled] → индекс 1 = лимит партий
  fireEvent.click(screen.getAllByRole("switch")[1]); // включить лимит
  fireEvent.click(screen.getByRole("button", { name: /Сохранить/i }));
  // показан диалог подтверждения, НЕ прямое сохранение
  expect(screen.getByText(/удалит старейшие партии/i)).toBeInTheDocument();
  expect(settingsApi.saveSettings).not.toHaveBeenCalled();
});

it("кнопка пароля disabled пока новый пароль короче 6 символов", async () => {
  render(<SettingsPage />);
  await screen.findByRole("heading", { name: /Настройки/i });
  fireEvent.change(screen.getByLabelText(/Текущий пароль/i), { target: { value: "pw" } });
  fireEvent.change(screen.getByLabelText(/Новый пароль/i), { target: { value: "123" } });
  expect(screen.getByRole("button", { name: /Обновить пароль/i })).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/Новый пароль/i), { target: { value: "123456" } });
  expect(screen.getByRole("button", { name: /Обновить пароль/i })).not.toBeDisabled();
});
