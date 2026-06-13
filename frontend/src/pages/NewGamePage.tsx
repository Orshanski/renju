import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getLevels, createGame } from "../game/api";
import type { LevelDTO } from "../game/types";
import styles from "./NewGamePage.module.css";

export default function NewGamePage() {
  const navigate = useNavigate();
  const [levels, setLevels] = useState<LevelDTO[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let alive = true;
    getLevels().then((l) => alive && setLevels(l)).catch(() => alive && setErr(true));
    return () => { alive = false; };
  }, []);

  async function pick(levelId: string) {
    if (busy) return;
    setBusy(true);
    try {
      const st = await createGame(levelId);
      navigate(`/game/${st.id}`);
    } catch {
      setBusy(false);
    }
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.eyebrow}>Новая партия</div>
      <h1 className={styles.title}>Выбери уровень</h1>
      {err && <p className={styles.sub}>Не удалось загрузить уровни.</p>}
      {levels === null && !err && <p className={styles.sub}>Загрузка…</p>}
      <div className={styles.levels}>
        {levels?.map((l) => (
          <button key={l.id} type="button" className={styles.level} disabled={busy} onClick={() => pick(l.id)}>
            {l.name}
          </button>
        ))}
      </div>
    </div>
  );
}
