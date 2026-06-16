import { it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "../api/client";

// Мокаем admin.api до импорта компонента
vi.mock("./admin.api", () => ({
  listUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  deleteUser: vi.fn(),
}));

import * as adminApi from "./admin.api";
import { UsersTab } from "./UsersTab";

const MOCK_USERS = [
  { id: 1, username: "alice", role: "admin" as const, created_at: "2026-06-17T10:00:00" },
  { id: 2, username: "bob", role: "user" as const, created_at: "2026-06-15T08:30:00" },
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(adminApi.listUsers).mockResolvedValue(MOCK_USERS);
  vi.mocked(adminApi.createUser).mockResolvedValue({ id: 3 });
  vi.mocked(adminApi.updateUser).mockResolvedValue({ ok: true });
  vi.mocked(adminApi.deleteUser).mockResolvedValue({ ok: true });
});

it("рендерит список пользователей с именем, ролью-бейджем и датой DD.MM.YYYY", async () => {
  render(<UsersTab currentUserId={99} />);

  expect(await screen.findByText("alice")).toBeInTheDocument();
  expect(screen.getByText("bob")).toBeInTheDocument();

  // Роли — бейджи с data-role
  const adminBadge = screen.getByText("Админ");
  expect(adminBadge).toHaveAttribute("data-role", "admin");
  const userBadge = screen.getByText("Игрок");
  expect(userBadge).toHaveAttribute("data-role", "user");

  // Дата в формате DD.MM.YYYY
  expect(screen.getByText("17.06.2026")).toBeInTheDocument();
  expect(screen.getByText("15.06.2026")).toBeInTheDocument();
});

it("кнопка «удалить» скрыта для строки с currentUserId", async () => {
  render(<UsersTab currentUserId={1} />);

  await screen.findByText("alice");

  // Для alice (id=1 = currentUserId) кнопки удалить не должно быть
  const deleteButtons = screen.getAllByRole("button", { name: /удалить/i });
  // Должна быть только одна кнопка удалить (для bob)
  expect(deleteButtons).toHaveLength(1);
});

it("клик «удалить» → модалка подтверждения → подтвердить → deleteUser вызван → список ре-фетчнут", async () => {
  const user = userEvent.setup();
  render(<UsersTab currentUserId={99} />);

  await screen.findByText("alice");

  // Кликаем удалить у alice (первая кнопка «удалить»)
  const deleteButtons = screen.getAllByRole("button", { name: /удалить/i });
  await user.click(deleteButtons[0]);

  // Модалка подтверждения
  const dialog = screen.getByRole("dialog");
  expect(dialog).toBeInTheDocument();
  expect(within(dialog).getByText(/удалить пользователя/i)).toBeInTheDocument();

  // Подтверждаем — кнопка «Подтвердить» внутри модалки
  await user.click(within(dialog).getByRole("button", { name: "Подтвердить" }));

  await waitFor(() => {
    expect(vi.mocked(adminApi.deleteUser)).toHaveBeenCalledWith(1);
  });
  await waitFor(() => {
    expect(vi.mocked(adminApi.listUsers)).toHaveBeenCalledTimes(2);
  });
});

it("клик «Завести пользователя» → модалка → submit → createUser вызван → список ре-фетчнут", async () => {
  const user = userEvent.setup();
  render(<UsersTab currentUserId={99} />);

  await screen.findByText("alice");

  await user.click(screen.getByRole("button", { name: /завести пользователя/i }));

  // Модалка создания
  const dialog = screen.getByRole("dialog");
  expect(dialog).toBeInTheDocument();

  // Заполняем форму
  await user.type(within(dialog).getByLabelText(/имя пользователя/i), "charlie");
  await user.type(within(dialog).getByLabelText(/пароль/i), "pass123");

  // Выбираем роль «Игрок»
  await user.click(within(dialog).getByRole("button", { name: "Игрок" }));

  await user.click(within(dialog).getByRole("button", { name: "Создать" }));

  await waitFor(() => {
    expect(vi.mocked(adminApi.createUser)).toHaveBeenCalledWith({
      username: "charlie",
      password: "pass123",
      role: "user",
    });
  });
  await waitFor(() => {
    expect(vi.mocked(adminApi.listUsers)).toHaveBeenCalledTimes(2);
  });
});

it("создать пользователя → ошибка 409 → показан error.detail, модалка не закрылась", async () => {
  vi.mocked(adminApi.createUser).mockRejectedValue(new ApiError(409, "Имя уже занято"));
  const user = userEvent.setup();
  render(<UsersTab currentUserId={99} />);

  await screen.findByText("alice");

  await user.click(screen.getByRole("button", { name: /завести пользователя/i }));

  const dialog = screen.getByRole("dialog");
  await user.type(within(dialog).getByLabelText(/имя пользователя/i), "alice");
  await user.type(within(dialog).getByLabelText(/пароль/i), "pass");
  await user.click(within(dialog).getByRole("button", { name: "Создать" }));

  await waitFor(() => {
    expect(screen.getByText("Имя уже занято")).toBeInTheDocument();
  });
  // Модалка остаётся открытой
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});

it("клик «роль» → модалка → выбор → submit → updateUser вызван с { role }", async () => {
  const user = userEvent.setup();
  render(<UsersTab currentUserId={99} />);

  await screen.findByText("alice");

  const roleButtons = screen.getAllByRole("button", { name: "Роль" });
  await user.click(roleButtons[0]);

  // Модалка смены роли
  const dialog = screen.getByRole("dialog");
  expect(dialog).toBeInTheDocument();

  // Выбираем роль «Игрок»
  await user.click(within(dialog).getByRole("button", { name: "Игрок" }));
  await user.click(within(dialog).getByRole("button", { name: "Применить" }));

  await waitFor(() => {
    expect(vi.mocked(adminApi.updateUser)).toHaveBeenCalledWith(1, { role: "user" });
  });
});

it("смена роли → ошибка 409 → показан error.detail", async () => {
  vi.mocked(adminApi.updateUser).mockRejectedValue(new ApiError(409, "Нельзя понизить последнего админа"));
  const user = userEvent.setup();
  render(<UsersTab currentUserId={99} />);

  await screen.findByText("alice");

  const roleButtons = screen.getAllByRole("button", { name: "Роль" });
  await user.click(roleButtons[0]);

  const dialog = screen.getByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Игрок" }));
  await user.click(within(dialog).getByRole("button", { name: "Применить" }));

  await waitFor(() => {
    expect(screen.getByText("Нельзя понизить последнего админа")).toBeInTheDocument();
  });
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});

it("клик «сброс пароля» → модалка → submit → updateUser вызван с { password }", async () => {
  const user = userEvent.setup();
  render(<UsersTab currentUserId={99} />);

  await screen.findByText("alice");

  const resetButtons = screen.getAllByRole("button", { name: /сброс пароля/i });
  await user.click(resetButtons[0]);

  const dialog = screen.getByRole("dialog");
  expect(dialog).toBeInTheDocument();

  await user.type(within(dialog).getByLabelText(/новый пароль/i), "newpass123");
  await user.click(within(dialog).getByRole("button", { name: "Применить" }));

  await waitFor(() => {
    expect(vi.mocked(adminApi.updateUser)).toHaveBeenCalledWith(1, { password: "newpass123" });
  });
});

it("сброс пароля на себе → после успеха logout() вызван", async () => {
  const mockLogout = vi.fn().mockResolvedValue(undefined);
  const user = userEvent.setup();
  render(<UsersTab currentUserId={1} logout={mockLogout} />);

  await screen.findByText("alice");

  // alice — текущий юзер (id=1); кликаем её кнопку «сброс пароля»
  const resetButtons = screen.getAllByRole("button", { name: /сброс пароля/i });
  await user.click(resetButtons[0]);

  const dialog = screen.getByRole("dialog");
  await user.type(within(dialog).getByLabelText(/новый пароль/i), "newpass");
  await user.click(within(dialog).getByRole("button", { name: "Применить" }));

  await waitFor(() => {
    expect(mockLogout).toHaveBeenCalledOnce();
  });
});
