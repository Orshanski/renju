import { useState, type SyntheticEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import styles from "./LoginPage.module.css";

// Визуал — по prototype/index.html §LOGIN (двухколоночная сцена: арт + форма).
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
    <div className={styles.stage}>
      <div className={styles.art}>
        <div className={styles.hanko}>連</div>
        <div className={styles.big}>
          <span className={styles.k}>連珠</span>
          <span className={styles.l}>Renju</span>
        </div>
        <div className={styles.poem}>
          <span className={styles.poemKanji}>斧の柄の<br />いくたび朽ちて<br />日永哉</span>
          <span className={styles.poemRu}>Рукоять топора<br />истлела —<br />смотрю на игру</span>
          <span className={styles.poemSig}>正岡子規 · 1895</span>
        </div>
        <div className={styles.gridDeco} />
      </div>
      <form className={styles.form} onSubmit={onSubmit}>
        <div className={styles.hanko}>入</div>
        <h1 className={styles.title}>С возвращением</h1>
        <p className={styles.sub}>Войдите, чтобы продолжить партию</p>
        <div className={styles.field}>
          <label htmlFor="username">Имя</label>
          <input id="username" value={username}
            onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </div>
        <div className={styles.field}>
          <label htmlFor="password">Пароль</label>
          <input id="password" type="password" value={password}
            onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </div>
        {error && <div className={styles.error}>{error}</div>}
        <button className={styles.button} type="submit" disabled={busy}>Войти</button>
        <p className={styles.note}>Регистрации нет — пользователей заводит администратор.</p>
      </form>
    </div>
  );
}
