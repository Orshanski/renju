import { Outlet, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useOnlineStatus } from "../hooks/useOnlineStatus";
import styles from "./Shell.module.css";

// Каркас — по prototype/index.html §App chrome (бренд + навбар + юзерчип).
export function Shell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const online = useOnlineStatus();

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true }); // явно: logout самодостаточен; ProtectedRoute-редирект — бэкстоп
  }

  // Активная вкладка: Админ → /admin*, Настройки → /settings*, Партии — дефолт
  const activeTab = pathname.startsWith("/admin")
    ? "admin"
    : pathname.startsWith("/settings")
      ? "settings"
      : "games";

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
        <nav className={styles.tabs}>
          <button
            className={`${styles.tab}${activeTab === "games" ? ` ${styles.active}` : ""}`}
            aria-current={activeTab === "games" ? "page" : undefined}
            onClick={() => navigate("/")}
          >
            Партии
          </button>
          <button
            className={`${styles.tab}${activeTab === "settings" ? ` ${styles.active}` : ""}`}
            aria-current={activeTab === "settings" ? "page" : undefined}
            onClick={() => navigate("/settings")}
          >
            Настройки
          </button>
          {user?.role === "admin" && (
            <button
              className={`${styles.tab}${activeTab === "admin" ? ` ${styles.active}` : ""}`}
              aria-current={activeTab === "admin" ? "page" : undefined}
              onClick={() => navigate("/admin")}
            >
              Админ
            </button>
          )}
        </nav>
        <div className={styles.spacer} />
        <div className={styles.userchip}>
          {/* ?. — гейт ProtectedRoute гарантирует user; страховка, не флоу */}
          <span className={styles.av}>{user?.username.charAt(0).toUpperCase()}</span>
          <span>{user?.username}</span>
          <button className={styles.linkbtn} onClick={onLogout}>выйти</button>
        </div>
      </header>
      {!online && (
        <div className={styles.offlineBar} role="status">
          Нет связи — проверьте соединение
        </div>
      )}
      <main className={styles.main}><Outlet /></main>
    </div>
  );
}
