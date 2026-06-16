import styles from "./SettingsPage.module.css";

// Заглушка — настоящий экран (undo-лимиты и пр.) будет в отдельном тикете.
export default function SettingsPage() {
  return (
    <div className={styles.wrap}>
      <div className={styles.eyebrow}>Профиль</div>
      <h1 className={styles.title}>Настройки</h1>
      <p className={styles.stub}>Настройки профиля и движка — в будущих релизах.</p>
    </div>
  );
}
