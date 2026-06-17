import { useState } from "react";
import { EngineTab } from "./EngineTab";
import { UsersTab } from "./UsersTab";
import { useAuth } from "../auth/AuthContext";
import styles from "./AdminPage.module.css";

type Tab = "users" | "engine" | "health";

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("users");
  const { user, logout } = useAuth();
  return (
    <div className={styles.wrap}>
      <div className={styles.eyebrow}>Администрирование</div>
      <h1 className={styles.title}>Управление</h1>
      <div className={styles.tabs}>
        <button className={tab === "users" ? styles.active : ""} onClick={() => setTab("users")}>Пользователи</button>
        <button className={tab === "engine" ? styles.active : ""} onClick={() => setTab("engine")}>Движок</button>
        <button className={tab === "health" ? styles.active : ""} onClick={() => setTab("health")}>Состояние</button>
      </div>
      {tab === "engine" && <EngineTab />}
      {tab === "users" && <UsersTab currentUserId={user!.id} logout={logout} />}
      {tab === "health" && <p className={styles.stub}>Состояние и здоровье движка — в будущих релизах.</p>}
    </div>
  );
}
