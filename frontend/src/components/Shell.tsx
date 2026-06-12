import { Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import styles from "./Shell.module.css";

export function Shell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true }); // явно: logout самодостаточен; ProtectedRoute-редирект — бэкстоп
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <span className={styles.brand}>Рэндзю</span>
        <div className={styles.right}>
          <span>{user?.username}</span>{/* ?. — гейт ProtectedRoute гарантирует user; страховка, не флоу */}
          <button className={styles.logout} onClick={onLogout}>Выход</button>
        </div>
      </header>
      <main className={styles.main}><Outlet /></main>
    </div>
  );
}
