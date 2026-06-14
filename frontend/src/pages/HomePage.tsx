import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getGamesSummary, getLevels } from "../game/api";
import type { GameSummaryDTO, Section } from "../game/types";
import { GameCard } from "../components/GameCard";
import styles from "./HomePage.module.css";

const TABS: { section: Section; label: string }[] = [
  { section: "current", label: "Текущие" },
  { section: "finished", label: "Завершённые" },
  { section: "favorite", label: "Избранное" },
];

export default function HomePage() {
  const navigate = useNavigate();
  const [section, setSection] = useState<Section>("current");
  const [games, setGames] = useState<GameSummaryDTO[] | null>(null);
  const [levelNames, setLevelNames] = useState<Map<string, string>>(new Map()); // id→имя для уровня-pill карточки
  const [reloadKey, setReloadKey] = useState(0); // bump → перезапрос текущего раздела после действия (favorite/delete)

  useEffect(() => {
    let alive = true;
    // имена уровней — справочник для карточек; отказ не критичен (pill просто не покажется)
    getLevels().then((ls) => alive && setLevelNames(new Map(ls.map((l) => [l.id, l.name])))).catch(() => {});
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    let alive = true; // guard от гонки: ответ устаревшего раздела не перетирает свежий при быстром переключении табов
    getGamesSummary(section).then((g) => alive && setGames(g)).catch(() => alive && setGames([]));
    return () => { alive = false; };
  }, [section, reloadKey]);

  return (
    <div className={styles.wrap}>
      <div className={styles.head}>
        <div>
          <div className={styles.eyebrow}>Твои партии</div>
          <h1 className={styles.title}>Доска ждёт</h1>
          <p className={styles.sub}>Продолжай с любого устройства — партия живёт на сервере.</p>
        </div>
        <button type="button" className={styles.newBtn} onClick={() => navigate("/new")}>＋ Новая партия</button>
      </div>
      <div className={styles.tabs} role="tablist">
        {TABS.map((t) => (
          <button key={t.section} role="tab" aria-selected={section === t.section}
            className={section === t.section ? styles.tabActive : styles.tab}
            onClick={() => setSection(t.section)}>{t.label}</button>
        ))}
      </div>
      {games === null && <p className={styles.sub}>Загрузка…</p>}
      {games !== null && games.length === 0 && <p className={styles.sub}>Здесь пусто.</p>}
      <div className={styles.grid}>
        {games?.map((g) => (
          <GameCard
            key={g.id}
            game={g}
            levelName={g.level_id ? levelNames.get(g.level_id) : undefined}
            onOpen={(id) => navigate(`/game/${id}`)}
            onChanged={() => setReloadKey((k) => k + 1)}
          />
        ))}
      </div>
    </div>
  );
}
