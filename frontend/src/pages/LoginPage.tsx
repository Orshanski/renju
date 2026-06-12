import { useState, type SyntheticEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import styles from "./LoginPage.module.css";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: SyntheticEvent) {
    e.preventDefault();
    if (busy) return; // гард двойного сабмита: Enter повторно, пока идёт запрос
    setBusy(true);
    setError("");
    try {
      await login(username, password);
      navigate("/", { replace: true });
    } catch (err) {
      setPassword("");
      if (err instanceof ApiError && err.status === 401) setError("Неверные имя или пароль");
      else if (err instanceof ApiError && err.status === 429) setError("Слишком много попыток, повторите позже");
      else setError("Ошибка входа");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.wrap}>
      <form className={styles.card} onSubmit={onSubmit}>
        <div className={styles.field}>
          <label htmlFor="username">Имя</label>
          <input id="username" className={styles.input} value={username}
            onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </div>
        <div className={styles.field}>
          <label htmlFor="password">Пароль</label>
          <input id="password" type="password" className={styles.input} value={password}
            onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </div>
        {error && <div className={styles.error}>{error}</div>}
        <button className={styles.button} type="submit" disabled={busy}>Войти</button>
      </form>
    </div>
  );
}
