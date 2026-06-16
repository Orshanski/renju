import { Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import styles from "./Shell.module.css";

// Каркас — по prototype/index.html §App chrome (бренд + юзерчип; табы появятся со срезами 2–5).
export function Shell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true }); // явно: logout самодостаточен; ProtectedRoute-редирект — бэкстоп
  }

  return (
    <div className={styles.shell}>
      <header className={styles.bar}>
        {/* бренд → главный экран: выход с игрового экрана (недопорт прототипа, rj-h0y).
            div + role/tabindex/keydown, а не <button> — тип элемента не меняем, чтобы
            не задеть верстку шапки; доступно с клавиатуры (Enter/Space). */}
        <div
          className={styles.brand}
          role="button"
          tabIndex={0}
          onClick={() => navigate("/")}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              navigate("/");
            }
          }}
        >
          <span className={styles.kanji}>連珠</span>
          <span className={styles.lat}>Renju</span>
        </div>
        <div className={styles.spacer} />
        <div className={styles.userchip}>
          {/* ?. — гейт ProtectedRoute гарантирует user; страховка, не флоу */}
          <span className={styles.av}>{user?.username.charAt(0).toUpperCase()}</span>
          <span>{user?.username}</span>
          {user?.role === "admin" && (
            <button className={styles.linkbtn} onClick={() => navigate("/admin")}>Админ</button>
          )}
          <button className={styles.linkbtn} onClick={onLogout}>выйти</button>
        </div>
      </header>
      <main className={styles.main}><Outlet /></main>
    </div>
  );
}
