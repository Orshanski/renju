// frontend/src/pages/SettingsPage.tsx
import { useEffect, useState } from "react";
import { bulkDeleteGames } from "../game/api";
import {
  type UserSettings,
  changePassword,
  getSettings,
  saveSettings,
} from "../settings.api";
import styles from "./SettingsPage.module.css";

type ConfirmKind = "delete-current" | "delete-finished" | "save-limit" | null;

export default function SettingsPage() {
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [draft, setDraft] = useState<UserSettings | null>(null);
  const [savingSettings, setSavingSettings] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmKind>(null);

  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [pwError, setPwError] = useState("");
  const [savingPw, setSavingPw] = useState(false);

  useEffect(() => {
    getSettings().then((s) => {
      setSettings(s);
      setDraft(s);
    });
  }, []);

  if (!settings || !draft) {
    return (
      <div className={styles.wrap}>
        <div className={styles.eyebrow}>Профиль</div>
        <h1 className={styles.title}>Настройки</h1>
      </div>
    );
  }

  const isDirty =
    draft.games_limit !== settings.games_limit ||
    draft.games_limit_enabled !== settings.games_limit_enabled ||
    draft.undo_enabled !== settings.undo_enabled ||
    draft.undo_limit !== settings.undo_limit ||
    draft.undo_after_game_end !== settings.undo_after_game_end;

  function handleSaveSettings() {
    // Лимит «ужесточается» = он включён И (был выключен ИЛИ число уменьшилось).
    // Оба случая удаляют партии сверх предела → подтверждаем.
    const limitTightened =
      draft!.games_limit_enabled &&
      (!settings!.games_limit_enabled || draft!.games_limit < settings!.games_limit);
    if (limitTightened) {
      setConfirm("save-limit");
    } else {
      doSaveSettings();
    }
  }

  function doSaveSettings() {
    setSavingSettings(true);
    saveSettings(draft!)
      .then((s) => {
        setSettings(s);
        setDraft(s);
      })
      .finally(() => setSavingSettings(false));
  }

  async function handleChangePw() {
    setPwError("");
    setSavingPw(true);
    try {
      await changePassword(curPw, newPw);
      setCurPw("");
      setNewPw("");
    } catch (e: unknown) {
      setPwError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setSavingPw(false);
    }
  }

  async function doBulkDelete(section: "current" | "finished") {
    await bulkDeleteGames(section);
    setConfirm(null);
  }

  const confirmText: Record<Exclude<ConfirmKind, null>, { title: string; body: string; action: () => void }> = {
    "delete-current": {
      title: "Удалить текущие партии",
      body: "Удалить все текущие партии? Это действие нельзя отменить.",
      action: () => doBulkDelete("current"),
    },
    "delete-finished": {
      title: "Удалить завершённые партии",
      body: "Удалить все завершённые партии? Это действие нельзя отменить.",
      action: () => doBulkDelete("finished"),
    },
    "save-limit": {
      title: "Применить лимит партий",
      body: "Лимит удалит старейшие партии сверх предела. Продолжить?",
      action: () => { setConfirm(null); doSaveSettings(); },
    },
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.eyebrow}>Профиль</div>
      <h1 className={styles.title}>Настройки</h1>

      {/* Откаты */}
      <div className={styles.sectionTitle}>Откаты</div>
      <div className={styles.settings}>
        <div className={styles.setrow}>
          <div>
            <div className={styles.setrowLabel}>Отмена ходов (undo)</div>
            <div className={styles.setrowDesc}>Разрешить откатывать ходы во время игры.</div>
          </div>
          <div
            className={draft.undo_enabled ? styles.toggleOn : styles.toggle}
            onClick={() => setDraft({ ...draft, undo_enabled: !draft.undo_enabled })}
            role="switch"
            aria-checked={draft.undo_enabled}
          />
        </div>

        {draft.undo_enabled && (
          <>
            <div className={styles.setrow}>
              <div>
                <div className={styles.setrowLabel}>Лимит откатов</div>
                <div className={styles.setrowDesc}>Сколько раз за партию можно отменить ход. ∞ — без ограничений.</div>
              </div>
              <div className={styles.stepper}>
                <button
                  className={styles.stepperBtn}
                  onClick={() =>
                    setDraft({ ...draft, undo_limit: draft.undo_limit === 1 ? null : draft.undo_limit !== null ? draft.undo_limit - 1 : null })
                  }
                >−</button>
                <div className={styles.stepperNum}>
                  {draft.undo_limit === null ? "∞" : draft.undo_limit}
                </div>
                <button
                  className={styles.stepperBtn}
                  onClick={() =>
                    setDraft({ ...draft, undo_limit: draft.undo_limit === null ? 1 : Math.min(999, draft.undo_limit + 1) })
                  }
                >+</button>
              </div>
            </div>

            <div className={styles.setrow}>
              <div>
                <div className={styles.setrowLabel}>Откат после конца партии</div>
                <div className={styles.setrowDesc}>Позволить вернуться в игру из завершённой партии.</div>
              </div>
              <div
                className={draft.undo_after_game_end ? styles.toggleOn : styles.toggle}
                onClick={() => setDraft({ ...draft, undo_after_game_end: !draft.undo_after_game_end })}
                role="switch"
                aria-checked={draft.undo_after_game_end}
              />
            </div>
          </>
        )}
      </div>

      {/* Управление партиями */}
      <div className={styles.sectionTitle}>Управление партиями</div>
      <div className={styles.settings}>
        <div className={styles.setrow}>
          <div>
            <div className={styles.setrowLabel}>Партий на раздел</div>
            <div className={styles.setrowDesc}>Верхний предел партий в каждом разделе (текущие / завершённые). 10–100.</div>
          </div>
          <div className={styles.limitControl}>
            <div
              className={draft.games_limit_enabled ? styles.toggleOn : styles.toggle}
              onClick={() => setDraft({ ...draft, games_limit_enabled: !draft.games_limit_enabled })}
              role="switch"
              aria-checked={draft.games_limit_enabled}
            />
            {draft.games_limit_enabled && (
              <div className={styles.stepper}>
                <button
                  className={styles.stepperBtn}
                  onClick={() => setDraft({ ...draft, games_limit: Math.max(10, draft.games_limit - 10) })}
                >−</button>
                <div className={styles.stepperNum}>{draft.games_limit}</div>
                <button
                  className={styles.stepperBtn}
                  onClick={() => setDraft({ ...draft, games_limit: Math.min(100, draft.games_limit + 10) })}
                >+</button>
              </div>
            )}
          </div>
        </div>
        <div className={styles.setrow}>
          <div>
            <div className={styles.setrowLabel}>Удалить текущие</div>
            <div className={styles.setrowDesc}>Стереть все незавершённые партии.</div>
          </div>
          <button className={styles.dangerRowBtn} onClick={() => setConfirm("delete-current")}>
            Удалить все
          </button>
        </div>
        <div className={styles.setrow}>
          <div>
            <div className={styles.setrowLabel}>Удалить завершённые</div>
            <div className={styles.setrowDesc}>Стереть все сыгранные партии.</div>
          </div>
          <button className={styles.dangerRowBtn} onClick={() => setConfirm("delete-finished")}>
            Удалить все
          </button>
        </div>
      </div>

      <button
        className={styles.saveBtn}
        disabled={!isDirty || savingSettings}
        onClick={handleSaveSettings}
      >
        {savingSettings ? "Сохранение…" : "Сохранить"}
      </button>

      {/* Сменить пароль */}
      <div className={styles.passwordBlock}>
        <div className={styles.sectionTitle}>Сменить пароль</div>
        <div className={styles.field}>
          <label htmlFor="cur-pw">Текущий пароль</label>
          <input id="cur-pw" type="password" value={curPw} onChange={(e) => setCurPw(e.target.value)} />
        </div>
        <div className={styles.field}>
          <label htmlFor="new-pw">Новый пароль</label>
          <input id="new-pw" type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
          <span className={styles.hint}>Минимум 6 символов.</span>
        </div>
        <p className={styles.hint}>После смены пароля другие устройства и вкладки будут отключены.</p>
        {pwError && <p className={styles.errMsg}>{pwError}</p>}
        <button
          className={styles.saveBtn}
          disabled={!curPw || newPw.length < 6 || savingPw}
          onClick={handleChangePw}
        >
          {savingPw ? "Сохранение…" : "Обновить пароль"}
        </button>
      </div>

      {/* Диалоги подтверждения */}
      {confirm && (
        <div className={styles.overlay} onClick={() => setConfirm(null)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalTitle}>{confirmText[confirm].title}</div>
            <p className={styles.modalBody}>{confirmText[confirm].body}</p>
            <div className={styles.modalFooter}>
              <button className={styles.cancelBtn} onClick={() => setConfirm(null)}>Отмена</button>
              <button className={styles.dangerBtn} onClick={confirmText[confirm].action}>
                {confirm === "save-limit" ? "Продолжить" : "Удалить все"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
