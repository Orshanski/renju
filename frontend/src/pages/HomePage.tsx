import styles from "./HomePage.module.css";

export default function HomePage() {
  return (
    <div className={styles.wrap}>
      <div className={styles.eyebrow}>Твои партии</div>
      <h1 className={styles.title}>Доска ждёт</h1>
      <p className={styles.sub}>Здесь будет список партий (срез 3).</p>
    </div>
  );
}
