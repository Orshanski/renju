import { useNavigate, useParams } from "react-router-dom";
import { useState, useEffect } from "react";
import { Board } from "../components/board/Board";
import { canPlay, canUndo, colorToMove, openingZone, pointLabel } from "../game/legality";
import type { UndoCfg } from "../game/legality";
import type { GameView } from "../game/view";
import { useGame } from "../game/useGame";
import { useLevels } from "../game/useLevels";
import { getSettings } from "../settings.api";
import styles from "./GamePage.module.css";

const COLOR_RU = { black: "чёрными", white: "белыми" } as const;

function turnText(view: GameView): string {
  switch (view.status) {
    case "finished_black":
      return "Победа чёрных ⚫";
    case "finished_white":
      return "Победа белых ⚪";
    case "finished_draw":
      return "Ничья";
    case "opponent_thinking":
      return "Ход соперника";
    case "awaiting_move":
      return colorToMove(view.moves.length) === view.yourColor ? "Твой ход" : "Ход соперника";
  }
}

export default function GamePage() {
  const { gameId } = useParams<{ gameId: string }>();
  const navigate = useNavigate();
  const { view, notice, play, undoMove, dismissNotice } = useGame(gameId!);
  const { nameOf } = useLevels();
  const [undoPolicy, setUndoPolicy] = useState<UndoCfg | null>(null);

  useEffect(() => {
    let active = true;
    getSettings().then((s) => {
      if (active) setUndoPolicy({ undo_enabled: s.undo_enabled, undo_limit: s.undo_limit, undo_after_game_end: s.undo_after_game_end });
    }).catch(() => { /* при ошибке остаёмся в null → кнопка disabled */ });
    return () => { active = false; };
  }, []);

  if (!view) return <div className={styles.loading}>{notice ?? "Загрузка…"}</div>;

  const myTurn = view.status === "awaiting_move" && colorToMove(view.moves.length) === view.yourColor;
  const zone = myTurn ? openingZone(view.moves.length) : null; // рамка видна только когда ввод за человеком
  const levelName = nameOf(view.opponentLevelId) ?? view.opponentLevelId ?? "—";
  const toMove = colorToMove(view.moves.length);

  return (
    <div className={styles.wrap}>
      {/* явный выход на главный экран (логотип-клик неочевиден, rj-h0y) */}
      <button type="button" className={styles.back} onClick={() => navigate("/")}>
        ← К партиям
      </button>
      <div className={styles.eyebrow}>
        Партия · ты играешь {view.yourColor ? COLOR_RU[view.yourColor] : "—"}
      </div>
      <div className={styles.layout}>
        <div className={styles.boardShell}>
          <Board
            moves={view.moves}
            forbidden={view.forbidden}
            zone={zone}
            winningLine={view.winningLine}
            ghostColor={toMove}
            canPlayAt={(x, y) => canPlay(view, [x, y])}
            onPlay={play}
          />
        </div>
        <aside className={styles.panel}>
          {notice && (
            <div className={styles.notice} role="status">
              <span>{notice}</span>
              <button type="button" className={styles.noticeClose} onClick={dismissNotice} aria-label="Закрыть">
                ✕
              </button>
            </div>
          )}
          <div className={styles.card}>
            <div className={styles.turn}>
              <span
                className={`${styles.bigstone} ${toMove === "black" ? styles.bigBlack : styles.bigWhite}`}
              />
              {/* индикатор «думает» — в той же строке, не вторым блоком: высота карточки
                  не прыгает (держится камнем-индикатором), текст может мигать (rj-p82) */}
              <div className={styles.who}>
                {view.status === "opponent_thinking" ? (
                  <span className={styles.thinking}>
                    <span className={styles.dot} />
                    <span className={styles.dot} />
                    <span className={styles.dot} />
                    соперник думает…
                  </span>
                ) : (
                  turnText(view)
                )}
              </div>
            </div>
          </div>
          <div className={styles.card}>
            <div className={styles.kv}>
              <span className={styles.k}>Уровень</span>
              <span className={styles.levelPill}>{levelName}</span>
            </div>
            <div className={styles.kv}>
              <span className={styles.k}>Твой цвет</span>
              <span className={styles.v}>{view.yourColor === "black" ? "чёрные ⚫" : "белые ⚪"}</span>
            </div>
            <div className={styles.kv}>
              <span className={styles.k}>Ход</span>
              <span className={styles.v}>№{view.moves.length}</span>
            </div>
            <div className={styles.kv}>
              <span className={styles.k}>Запрещённые</span>
              <span className={styles.legendForbid}>подсвечены ✕</span>
            </div>
          </div>
          <div className={styles.controls}>
            <button type="button" className={styles.undoBtn} disabled={undoPolicy === null || !canUndo(view, undoPolicy)} onClick={() => void undoMove()}>
              ↶ Отменить
            </button>
          </div>
          <div className={styles.card}>
            <div className={styles.eyebrow}>Лог ходов</div>
            <div className={styles.movelog} data-testid="movelog">
              {view.moves
                .map((m, i) => ({ m, i }))
                .reverse()
                .map(({ m, i }) => (
                  <div key={i}>
                    {i + 1}. <b>{i % 2 === 0 ? "⚫" : "⚪"}</b> {pointLabel(m)}
                  </div>
                ))}
            </div>
          </div>
          <div className={styles.attr}>
            <a href="https://www.vecteezy.com/free-photos/wood" target="_blank" rel="noopener noreferrer">
              Wood Stock photos by Vecteezy
            </a>
          </div>
        </aside>
      </div>
    </div>
  );
}
