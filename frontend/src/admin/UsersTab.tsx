import { useEffect, useState } from "react";
import { listUsers, createUser, updateUser, deleteUser, type UserAdminDTO } from "./admin.api";
import { ApiError } from "../api/client";
import styles from "./UsersTab.module.css";

type Props = {
  currentUserId: number;
  logout?: () => Promise<void>;
};

function formatDate(iso: string): string {
  return iso.split("T")[0].split("-").reverse().join(".");
}

type Modal =
  | { type: "create" }
  | { type: "resetPassword"; user: UserAdminDTO }
  | { type: "changeRole"; user: UserAdminDTO }
  | { type: "confirmDelete"; user: UserAdminDTO };

export function UsersTab({ currentUserId, logout }: Props) {
  const [users, setUsers] = useState<UserAdminDTO[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [modal, setModal] = useState<Modal | null>(null);

  function closeModal() {
    setModal(null);
  }

  async function fetchUsers() {
    try {
      const data = await listUsers();
      setUsers(data);
    } catch {
      setLoadErr("Не удалось загрузить список пользователей.");
    }
  }

  useEffect(() => {
    let alive = true;
    listUsers()
      .then((data) => { if (alive) setUsers(data); })
      .catch(() => { if (alive) setLoadErr("Не удалось загрузить список пользователей."); });
    return () => { alive = false; };
  }, []);

  if (loadErr && !users) return <p className={styles.sub}>{loadErr}</p>;
  if (!users) return <p className={styles.sub}>Загрузка…</p>;

  return (
    <div>
      <div className={styles.header}>
        <div />
        <button className={styles.addBtn} onClick={() => setModal({ type: "create" })}>
          ＋ Завести пользователя
        </button>
      </div>

      <table className={styles.tbl}>
        <thead>
          <tr>
            <th>Имя</th>
            <th>Роль</th>
            <th>Создан</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.username}</td>
              <td>
                <span className={styles.roleBadge} data-role={u.role}>
                  {u.role === "admin" ? "Админ" : "Игрок"}
                </span>
              </td>
              <td>{formatDate(u.created_at)}</td>
              <td>
                <div className={styles.actions}>
                  <button
                    className={styles.actionBtn}
                    onClick={() => setModal({ type: "resetPassword", user: u })}
                  >
                    Сброс пароля
                  </button>
                  <button
                    className={styles.actionBtn}
                    onClick={() => setModal({ type: "changeRole", user: u })}
                  >
                    Роль
                  </button>
                  {u.id !== currentUserId && (
                    <button
                      className={styles.actionBtnDanger}
                      onClick={() => setModal({ type: "confirmDelete", user: u })}
                    >
                      Удалить
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {modal?.type === "create" && (
        <CreateModal
          onClose={closeModal}
          onSuccess={() => { closeModal(); fetchUsers(); }}
        />
      )}

      {modal?.type === "resetPassword" && (
        <ResetPasswordModal
          user={modal.user}
          currentUserId={currentUserId}
          logout={logout}
          onClose={closeModal}
          onSuccess={closeModal}
        />
      )}

      {modal?.type === "changeRole" && (
        <ChangeRoleModal
          user={modal.user}
          onClose={closeModal}
          onSuccess={() => { closeModal(); fetchUsers(); }}
        />
      )}

      {modal?.type === "confirmDelete" && (
        <ConfirmDeleteModal
          user={modal.user}
          onClose={closeModal}
          onConfirm={async () => {
            await deleteUser(modal.user.id);
            closeModal();
            await fetchUsers();
          }}
        />
      )}
    </div>
  );
}

// --- Модалка «Создать пользователя» ---

function CreateModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "user">("user");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      await createUser({ username, password, role });
      onSuccess();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Не удалось создать.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <p className={styles.modalTitle}>Новый пользователь</p>
        <div className={styles.field}>
          <label htmlFor="create-username">Имя пользователя</label>
          <input
            id="create-username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
          />
        </div>
        <div className={styles.field}>
          <label htmlFor="create-password">Пароль</label>
          <input
            id="create-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className={styles.roleGroup}>
          <button
            type="button"
            className={role === "user" ? styles.roleChoiceActive : styles.roleChoice}
            onClick={() => setRole("user")}
          >
            Игрок
          </button>
          <button
            type="button"
            className={role === "admin" ? styles.roleChoiceActive : styles.roleChoice}
            onClick={() => setRole("admin")}
          >
            Админ
          </button>
        </div>
        {err && <p className={styles.errMsg}>{err}</p>}
        <div className={styles.modalFooter}>
          <button className={styles.cancelBtn} onClick={onClose}>Отмена</button>
          <button className={styles.submitBtn} disabled={busy} onClick={submit}>Создать</button>
        </div>
      </div>
    </div>
  );
}

// --- Модалка «Сброс пароля» ---

function ResetPasswordModal({
  user,
  currentUserId,
  logout,
  onClose,
  onSuccess,
}: {
  user: UserAdminDTO;
  currentUserId: number;
  logout?: () => Promise<void>;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      await updateUser(user.id, { password });
      if (user.id === currentUserId && logout) {
        await logout();
      }
      onSuccess();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Не удалось сбросить пароль.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <p className={styles.modalTitle}>Сброс пароля — {user.username}</p>
        <div className={styles.field}>
          <label htmlFor="reset-password">Новый пароль</label>
          <input
            id="reset-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
          />
        </div>
        {err && <p className={styles.errMsg}>{err}</p>}
        <div className={styles.modalFooter}>
          <button className={styles.cancelBtn} onClick={onClose}>Отмена</button>
          <button className={styles.submitBtn} disabled={busy} onClick={submit}>Применить</button>
        </div>
      </div>
    </div>
  );
}

// --- Модалка «Смена роли» ---

function ChangeRoleModal({
  user,
  onClose,
  onSuccess,
}: {
  user: UserAdminDTO;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [role, setRole] = useState<"admin" | "user">(user.role);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      await updateUser(user.id, { role });
      onSuccess();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Не удалось сменить роль.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <p className={styles.modalTitle}>Роль — {user.username}</p>
        <div className={styles.roleGroup}>
          <button
            type="button"
            className={role === "user" ? styles.roleChoiceActive : styles.roleChoice}
            onClick={() => setRole("user")}
          >
            Игрок
          </button>
          <button
            type="button"
            className={role === "admin" ? styles.roleChoiceActive : styles.roleChoice}
            onClick={() => setRole("admin")}
          >
            Админ
          </button>
        </div>
        {err && <p className={styles.errMsg}>{err}</p>}
        <div className={styles.modalFooter}>
          <button className={styles.cancelBtn} onClick={onClose}>Отмена</button>
          <button className={styles.submitBtn} disabled={busy} onClick={submit}>Применить</button>
        </div>
      </div>
    </div>
  );
}

// --- Модалка «Подтверждение удаления» ---

function ConfirmDeleteModal({
  user,
  onClose,
  onConfirm,
}: {
  user: UserAdminDTO;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);

  async function confirm() {
    if (busy) return;
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <p className={styles.modalTitle}>Удалить пользователя</p>
        <p className={styles.sub}>Удалить «{user.username}»? Это действие необратимо.</p>
        <div className={styles.modalFooter}>
          <button className={styles.cancelBtn} onClick={onClose}>Отмена</button>
          <button className={styles.dangerBtn} disabled={busy} onClick={confirm}>Подтвердить</button>
        </div>
      </div>
    </div>
  );
}
