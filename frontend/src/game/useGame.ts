import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest, ApiError } from "../api/client";
import { enterGame, getGame, leaveGame, postMove, postUndo } from "./api";
import { canPlay } from "./legality";
import { applyEvent, fromState, placePending } from "./reducer";
import type { GameEventMessage, Point } from "./types";
import type { GameView } from "./view";

const EVENT_TYPES = ["move", "status", "forbidden", "undo", "error", "reset"] as const;

/** Оркестрация партии: начальный GET, SSE с reconnect, оптимистичный ход, undo.
 *  Чистая логика — в reducer/legality; здесь только I/O и склейка (спека §«Поток данных»). */
export function useGame(gameId: string, reconnectDelayMs = 3000) {
  const [view, setView] = useState<GameView | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const viewRef = useRef<GameView | null>(null); // актуальное состояние для колбэков вне рендера
  const esRef = useRef<EventSource | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aliveRef = useRef(true);

  const commit = useCallback((v: GameView) => {
    viewRef.current = v;
    setView(v);
  }, []);

  const resync = useCallback(async () => {
    // сервер — источник истины; pending при ресинхроне сбрасывается вместе с заменой вью
    try {
      const st = await getGame(gameId);
      if (aliveRef.current) commit(fromState(st));
    } catch {
      if (aliveRef.current) setNotice("Не удалось загрузить партию");
    }
  }, [gameId, commit]);

  const handleEvent = useCallback(
    (ev: GameEventMessage) => {
      const cur = viewRef.current;
      if (!cur) return;
      if (ev.type === "error") setNotice("Движок споткнулся — партия продолжится автоматически");
      const next = applyEvent(cur, ev);
      if (next === "resync") void resync();
      else commit(next);
    },
    [resync, commit],
  );

  const connect = useCallback(
    (since: number) => {
      const es = new EventSource(`/api/games/${gameId}/events?since=${since}`);
      esRef.current = es;
      for (const t of EVENT_TYPES) {
        es.addEventListener(t, (e) => handleEvent(JSON.parse((e as MessageEvent).data) as GameEventMessage));
      }
      es.onerror = () => {
        es.close();
        if (timerRef.current) clearTimeout(timerRef.current); // повторный onerror не делает старый таймер неотменяемым
        timerRef.current = setTimeout(() => {
          void (async () => {
            try {
              // проверка сессии БЕЗ skipAuthRedirect: отозвана → глобальный 401-редирект,
              // вечный реконнект-цикл исключён (мастер-спека §10)
              await apiRequest("GET", "/api/auth/me");
            } catch (e) {
              if (e instanceof ApiError && e.status === 401) return; // сессия отозвана — стоп
              // сетевая ошибка / 5xx: сервер недоступен → продолжаем попытки через connect
              // (новый EventSource сразу уйдёт в onerror → снова таймер → /me; цикл с паузой)
              if (aliveRef.current) connect(viewRef.current?.cursor ?? since);
              return;
            }
            if (aliveRef.current) connect(viewRef.current?.cursor ?? since);
          })();
        }, reconnectDelayMs);
      };
    },
    [gameId, handleEvent, reconnectDelayMs],
  );

  useEffect(() => {
    aliveRef.current = true;
    void enterGame(gameId).catch(() => {}); // presence++: поднять/переиспользовать процесс партии (rj-899)
    void (async () => {
      try {
        const st = await getGame(gameId);
        if (!aliveRef.current) return;
        commit(fromState(st));
        connect(st.cursor); // курсор первого подключения — из GET-ответа (спека, M2)
      } catch {
        if (aliveRef.current) setNotice("Не удалось загрузить партию");
      }
    })();
    const onOnline = () => {
      // поток закрыт/отсутствует → переподключиться. readyState сравниваем с литералом 2
      // (CLOSED) — как везде в useGame; FakeEventSource в тестах не имеет статической
      // константы EventSource.CLOSED, и `=== EventSource.CLOSED` дало бы undefined.
      if (aliveRef.current && (esRef.current === null || esRef.current.readyState === 2)) {
        if (timerRef.current) clearTimeout(timerRef.current); // гасим висящий reconnect-таймер из onerror (без двойного connect)
        connect(viewRef.current?.cursor ?? 0);
      }
    };
    globalThis.addEventListener("online", onOnline);
    return () => {
      aliveRef.current = false;
      esRef.current?.close();
      if (timerRef.current) clearTimeout(timerRef.current);
      globalThis.removeEventListener("online", onOnline);
      void leaveGame(gameId).catch(() => {}); // presence--: гасим, если ушло последнее устройство
    };
  }, [gameId, connect, commit]);

  const play = useCallback(
    async (x: number, y: number) => {
      const cur = viewRef.current;
      const pt: Point = [x, y];
      if (!cur || !canPlay(cur, pt)) return; // нелегальный клик — тишина (ghost его и не покажет)
      commit(placePending(cur, pt));
      try {
        await postMove(gameId, x, y); // 202; подтверждение — своё SSE-move (могло прийти раньше ответа)
      } catch {
        if (!aliveRef.current) return;
        // view здесь заведомо не null (placePending выше), но пишем явно — ?.-форма давала бы true и при null
        if (viewRef.current !== null && viewRef.current.pendingIndex !== null) {
          // ещё не подтверждён → рассинхрон: откат + истина с сервера (спека, доктрина отказов)
          setNotice("Доска обновлена — ход не прошёл");
          await resync();
        }
        // уже подтверждён событием → исход POST игнорируем (первый из двух исходов решает)
      }
    },
    [gameId, commit, resync],
  );

  const undoMove = useCallback(async () => {
    try {
      const st = await postUndo(gameId); // ответ undo — полный state (cursor консистентен событиям)
      if (aliveRef.current) commit(fromState(st));
    } catch {
      if (!aliveRef.current) return;
      setNotice("Доска обновлена — действие не прошло");
      await resync();
    }
  }, [gameId, commit, resync]);

  const dismissNotice = useCallback(() => setNotice(null), []);

  return { view, notice, play, undoMove, dismissNotice };
}
