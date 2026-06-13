import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createGame } from "../game/api";
import styles from "./HomePage.module.css";

export default function HomePage() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  // Временная кнопка среза 2: хардкод novice. Заменяется экраном выбора уровня в срезе 3 (rj-as6).
  async function onNewGame() {
    if (busy) return;
    setBusy(true);
    try {
      const st = await createGame("novice");
      navigate(`/game/${st.id}`);
    } catch {
      setBusy(false); // осталась активной — можно повторить
    }
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.eyebrow}>Твои партии</div>
      <h1 className={styles.title}>Доска ждёт</h1>
      <p className={styles.sub}>Здесь будет список партий (срез 3).</p>
      <button type="button" className={styles.newBtn} onClick={onNewGame} disabled={busy}>
        ＋ Новая партия (Новичок)
      </button>
    </div>
  );
}
