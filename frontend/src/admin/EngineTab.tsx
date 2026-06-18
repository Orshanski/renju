import { useEffect, useState } from "react";
import { getEngineConfig, putEngineConfig } from "./admin.api";
import { depthRange, clampStrength } from "./levelDepth";
import { ApiError } from "../api/client";
import styles from "./EngineTab.module.css";

type Row = { id: string; name: string; strength: number; timeoutSec: number; depth: number };

export function EngineTab() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [nnue, setNnue] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    getEngineConfig()
      .then((c) => {
        if (!alive) return;
        setRows(c.levels.map((l) => ({
          id: l.id,
          name: l.name,
          strength: l.strength,
          timeoutSec: l.timeout_ms / 1000,
          depth: l.max_depth,
        })));
        setNnue(c.nnue);
      })
      .catch(() => alive && setErr("Не удалось загрузить настройки."));
    return () => { alive = false; };
  }, []);

  async function save() {
    if (!rows || busy) return;
    setBusy(true); setSaved(false); setErr(null);
    try {
      const c = await putEngineConfig({
        levels: rows.map((r) => ({
          id: r.id,
          strength: r.strength,
          timeout_ms: Math.round(r.timeoutSec * 1000),
          max_depth: r.depth,
        })),
        nnue,
      });
      setRows(c.levels.map((l) => ({
        id: l.id,
        name: l.name,
        strength: l.strength,
        timeoutSec: l.timeout_ms / 1000,
        depth: l.max_depth,
      })));
      setNnue(c.nnue);
      setSaved(true);
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Не удалось сохранить.");
    } finally {
      setBusy(false);
    }
  }

  if (err && !rows) return <p className={styles.sub}>{err}</p>;
  if (!rows) return <p className={styles.sub}>Загрузка…</p>;

  const setRow = (id: string, patch: Partial<Row>) => {
    setSaved(false);
    setRows((rs) => {
      const idx = rs!.findIndex((r) => r.id === id);
      let next = rs!.map((r) => (r.id === id ? { ...r, ...patch } : r));
      if (patch.strength !== undefined) {
        const strengths = next.map((r) => r.strength);
        const clamped = clampStrength(idx, patch.strength, strengths);
        strengths[idx] = clamped;
        const [, hi] = depthRange(idx, strengths);
        next = next.map((r, k) =>
          k === idx ? { ...r, strength: clamped, depth: Math.min(r.depth, hi) } : r,
        );
      }
      return next;
    });
  };

  const strengths = rows.map((r) => r.strength);

  return (
    <div>
      <p className={styles.sub}>Сила и время раздумий по уровням — калибруется на живой игре. Сила 0–100. Применяется к новым партиям.</p>
      <table className={styles.tbl}>
        <thead>
          <tr>
            <th>Уровень</th>
            <th>Сила (0–100)</th>
            <th>Глубина</th>
            <th>Время на ход, с</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const [lo, hi] = depthRange(i, strengths);
            return (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    aria-label={`${r.name} сила`}
                    value={r.strength}
                    onChange={(e) => setRow(r.id, { strength: Number(e.target.value) })}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    min={lo}
                    max={hi}
                    aria-label={`${r.name} глубина`}
                    value={r.depth}
                    onChange={(e) => setRow(r.id, { depth: Math.min(Math.max(Number(e.target.value), lo), hi) })}
                  />
                  <span className={styles.desc}>макс {hi}</span>
                </td>
                <td>
                  <input
                    type="number"
                    min={0.2}
                    step={0.5}
                    aria-label={`${r.name} время`}
                    value={r.timeoutSec}
                    onChange={(e) => setRow(r.id, { timeoutSec: Number(e.target.value) })}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className={styles.setrow}>
        <div>
          <div className={styles.label}>Нейросеть (NNUE)</div>
          <div className={styles.desc}>Полная сила движка. Выключить — режим на слабом CPU.</div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={nnue}
          aria-label="Нейросеть"
          className={nnue ? `${styles.toggle} ${styles.on}` : styles.toggle}
          onClick={() => { setNnue((v) => !v); setSaved(false); }}
        />
      </div>
      <div className={styles.actions}>
        <button className={styles.save} disabled={busy} onClick={save}>Сохранить</button>
        {saved && <span className={styles.ok}>Сохранено</span>}
        {err && rows && <span className={styles.errMsg}>{err}</span>}
      </div>
    </div>
  );
}
