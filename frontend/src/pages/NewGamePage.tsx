import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getLevels, createGame } from "../game/api";
import type { LevelDTO } from "../game/types";
import styles from "./NewGamePage.module.css";

// Иероглиф-«печать» уровня (визуальная деталь прототипа). Под глифом — название-перевод.
// Ключи — id уровней из levels.toml; глиф рисуется только при совпадении (неизвестный id → без глифа).
const KANJI: Record<string, string> = {
  novice: "初", // начало
  easy: "易", // лёгкий
  low_medium: "下", // ниже
  high_medium: "上", // выше
  hard: "難", // трудный
  master: "名", // мастер
  god: "神", // бог
};

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

  // Два центрированных ряда: короткий — сверху (floor(n/2)). Для 7 уровней → 3 + 4,
  // без одинокой плитки. Сплит data-driven — переживёт смену числа уровней в levels.toml.
  const rows = levels
    ? [levels.slice(0, Math.floor(levels.length / 2)), levels.slice(Math.floor(levels.length / 2))]
    : [];

  return (
    <div className={styles.wrap}>
      <div className={styles.eyebrow}>Новая партия</div>
      <h1 className={styles.title}>Выбери соперника</h1>
      {err && <p className={styles.sub}>Не удалось загрузить уровни.</p>}
      {levels === null && !err && <p className={styles.sub}>Загрузка…</p>}
      <div className={styles.levels}>
        {rows.map((row, ri) => (
          <div key={ri} className={styles.levelRow}>
            {row.map((l) => (
              <button key={l.id} type="button" className={styles.level} disabled={busy} onClick={() => pick(l.id)}>
                {KANJI[l.id] && <span className={styles.lk} aria-hidden="true">{KANJI[l.id]}</span>}
                <span className={styles.ln}>{l.name}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
      {levels && !err && (
        <div className={styles.dice}>🎲 Цвет выпадет случайно. Если белые — первый ход сделает движок.</div>
      )}
    </div>
  );
}
