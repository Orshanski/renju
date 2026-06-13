import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { GameSummaryDTO } from "../game/types";
import { favoriteGame, unfavoriteGame, deleteGame } from "../game/api";
import { statusLabel, sectionDateLabel } from "../game/format";
import styles from "./GameCard.module.css";

type Props = { game: GameSummaryDTO; onOpen: (id: string) => void; onChanged: () => void };

const LONG_TAP_MS = 500;

export function GameCard({ game, onOpen, onChanged }: Props) {
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  function openMenu(e: { preventDefault: () => void }) {
    e.preventDefault();
    setMenu(true);
  }
  function onPointerDown(e: ReactPointerEvent) {
    if (e.pointerType !== "touch") return; // long-tap — только на тач (спека §6); мышь — правый клик
    timer.current = window.setTimeout(() => setMenu(true), LONG_TAP_MS);
  }
  function cancelLongTap() {
    if (timer.current !== null) { clearTimeout(timer.current); timer.current = null; }
  }
  useEffect(() => cancelLongTap, []); // очистка висячего таймера при размонтировании

  async function run(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    // busy намеренно НЕ сбрасывается на успехе: после onChanged() родитель перезапросит
    // раздел и размонтирует эту карточку — застрявший busy недостижим.
    try { await action(); setMenu(false); onChanged(); }
    catch { setBusy(false); } // меню остаётся — можно повторить
  }

  return (
    <div
      data-testid={`card-${game.id}`}
      className={styles.card}
      role="button"
      tabIndex={0}
      onClick={() => onOpen(game.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(game.id);
        }
      }}
      onContextMenu={openMenu}
      onPointerDown={onPointerDown}
      onPointerUp={cancelLongTap}
      onPointerMove={cancelLongTap}
    >
      <div className={styles.status}>{statusLabel(game.status, game.your_color)}</div>
      <div className={styles.meta}>
        {game.level_id && <span>{game.level_id}</span>}
        <span>ход {game.move_count}</span>
        {game.your_color && <span>ты {game.your_color === "black" ? "чёрные" : "белые"}</span>}
      </div>
      <div className={styles.date}>{sectionDateLabel(game.section, game)}</div>

      {menu && (
        <>
          {/* backdrop перехватывает клик вне меню → dismiss; stopPropagation, чтобы
              pointerdown/click не всплыли к карточке и не открыли партию */}
          <div
            data-testid="menu-backdrop"
            className={styles.backdrop}
            onPointerDown={(e) => { e.stopPropagation(); setMenu(false); }}
            onClick={(e) => e.stopPropagation()}
          />
          <div className={styles.menu} role="menu" onClick={(e) => e.stopPropagation()}>
            {game.section === "finished" && (
              <button role="menuitem" disabled={busy} onClick={() => run(() => favoriteGame(game.id))}>В избранное</button>
            )}
            {game.section === "favorite" && (
              <button role="menuitem" disabled={busy} onClick={() => run(() => unfavoriteGame(game.id))}>Из избранного</button>
            )}
            <button role="menuitem" disabled={busy} onClick={() => run(() => deleteGame(game.id))}>Удалить</button>
          </div>
        </>
      )}
    </div>
  );
}
