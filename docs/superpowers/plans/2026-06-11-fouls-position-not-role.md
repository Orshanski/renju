# Фолы и валидация — от позиции, не от роли — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Убрать ролевую (человек/движок) связанность из правил и показа фолов, чтобы PvP/веб не наследовали баг. Фолы чёрных вычисляются и показываются от позиции (ход чёрных), а не от того, кто играет; валидация хода единообразна для любого источника.

**Architecture:** Домен и сервис уже почти нейтральны (`validate_move`, `apply_move`, `forbidden_points` — от позиции). Чиним два места: (1) имя параметра `undo_truncate(human_color=)` в домене; (2) `play_cli.game_loop` — фолы считаются один раз за полуход из позиции и идут и в показ (каждый полуход, включая ход движка), и в `apply_move` (и человеку, и движку). Статус-енумы `GameStatus.AWAITING_HUMAN/ENGINE_THINKING` — отдельно в `rj-8sc` (не здесь).

**Tech Stack:** Python 3.13 / uv / pytest / ruff. bd: `rj-dxe`.

**Команды:** из `backend/`. `uv run pytest -q` · `uv run pytest <путь>::<тест> -v` · `uv run ruff check app tests scripts` / `ruff format`. Pytest последовательно.

---

## File Structure

- `app/domain/game.py` (**править**) — `undo_truncate` параметр `human_color` → `for_color`.
- `tests/unit/test_game.py` (**править**) — undo-тесты: `human_color=` → `for_color=`.
- `scripts/play_cli.py` (**править**) — (Task 1) вызов `undo_truncate`; (Task 2) `game_loop` фолы от позиции.

**Вне скоупа (не трогать):** домен `validate_move`/`apply_move`/`forbidden_points` (уже нейтральны); статус-енумы (rj-8sc); ветка `human`/движок в драйвере play_cli (это HvE-smoke, легитимная оркестрация — течь была только в показе/валидации фолов).

---

## Task 1: Домен — нейтральное имя параметра `undo_truncate`

`human_color` говорит «human»; логика — по цвету («откатить к ходу этого цвета»). Домен не должен знать роль. Чистое переименование, поведение не меняется.

**Files:**
- Modify: `app/domain/game.py`
- Modify: `tests/unit/test_game.py`, `scripts/play_cli.py` (вызовы)

- [ ] **Step 1: Обновить вызовы в тестах (red)**

В `tests/unit/test_game.py` заменить во ВСЕХ undo-тестах `human_color=` на `for_color=`. Сейчас вызовы такие (6 штук):
```python
undo_truncate(moves=[(7, 7), (8, 8)], human_color=Color.BLACK)
undo_truncate(moves=moves, human_color=Color.BLACK)
undo_truncate(moves=moves, human_color=Color.WHITE)
undo_truncate(moves=moves, human_color=Color.WHITE)
undo_truncate(moves=[], human_color=Color.BLACK)
undo_truncate(moves=[(7, 7)], human_color=Color.WHITE)
```
Заменить каждый `human_color=` → `for_color=` (значения не трогать).

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `uv run pytest tests/unit/test_game.py -k undo -v`
Expected: FAIL (`undo_truncate() got an unexpected keyword argument 'for_color'`).

- [ ] **Step 3: Переименовать параметр в `game.py`**

В `app/domain/game.py` в `undo_truncate` заменить сигнатуру и тело:
```python
def undo_truncate(*, moves: Sequence[Point], for_color: Color, preset: int = 1) -> list[Point]:
    """Усечь ходы до предыдущего состояния «ход for_color», не снимая preset
    стартовых камней (центр предзаполнен). Новая длина k — наибольшая
    preset ≤ k < len(moves) c очередью for_color (k чётно для чёрных, нечётно для белых).
    Если такого k нет — NOTHING_TO_UNDO. (for_color — сторона, для которой откат;
    источник хода — человек/ИИ — не важен.)"""
    target_parity = 0 if for_color is Color.BLACK else 1
    k = len(moves) - 1
    while k >= preset and k % 2 != target_parity:
        k -= 1
    if k < preset:
        raise UndoRejected(UndoRejectReason.NOTHING_TO_UNDO)
    return list(moves[:k])
```

- [ ] **Step 4: Обновить вызов в `play_cli.py`**

В `scripts/play_cli.py` найти `undo_truncate(moves=moves, human_color=human)` и заменить на:
```python
                    moves = undo_truncate(moves=moves, for_color=human)
```

- [ ] **Step 5: Прогнать — зелёный**

Run: `uv run pytest tests/unit/test_game.py -v` (и полный `uv run pytest -q` — поведение не менялось, всё зелёное).
Expected: PASS.

- [ ] **Step 6: Линт + коммит**

```bash
uv run ruff check app tests scripts && uv run ruff format app tests scripts
git add app/domain/game.py tests/unit/test_game.py scripts/play_cli.py
git commit -m "refactor(domain): undo_truncate human_color -> for_color (домен без роли)"
```

---

## Task 2: play_cli — фолы и валидация от позиции

`game_loop` сейчас (стр. ~73-110): фолы считаются только в ветке человека и только `if human is Color.BLACK`, доска рендерится только на ходу человека, а ход движка применяется с `forbidden=[]`. Чиним: считать `forbidden = await adapter.forbidden_points(moves)` один раз в начале каждого полухода (адаптер сам отдаёт `[]`, когда на ходу белые), рендерить доску каждый полуход (в т.ч. на ходу движка — чтобы белый-человек видел фолы чёрного-движка), и отдавать этот `forbidden` в `apply_move` и человеку, и движку.

**Files:**
- Modify: `scripts/play_cli.py` (`game_loop`)

**Тестирование:** механизм показа фолов (`×` из `forbidden`) уже покрыт юнит-тестом `test_render_board_smoke` (`render_board` с `forbidden`). Сам `game_loop` — интерактивная smoke-петля (создаёт адаптер, читает `input()`), юнит-тестами не покрывалась и не покрывается в этом этапе; её проводку проверяет **ручной smoke Alexey** (шаг 10 флоу): партия за белых — на ходу движка-чёрного видны `×`. Поэтому здесь TDD-red-теста нет — это переустройство проводки harness, не новая чистая логика.

- [ ] **Step 1: Переписать цикл `game_loop` — фолы от позиции, рендер каждый полуход**

В `scripts/play_cli.py` заменить тело цикла `while True:` в `game_loop` на:
```python
    moves: list[Point] = new_game()
    try:
        while True:
            forbidden = await adapter.forbidden_points(moves)  # фолы чёрных; непусто только когда их ход
            human_turn = color_to_move(len(moves)) is human
            zone = opening_zone(len(moves)) if human_turn else None
            print(render_board(moves=moves, forbidden=forbidden, zone=zone))

            if not human_turn:
                print("… соперник думает")
                engine_pt = await engine_move(adapter, moves, params)
                moves = apply_move(moves, engine_pt, forbidden=forbidden)
                outcome = outcome_after(moves)
                if outcome is not None:
                    print(render_board(moves=moves, forbidden=[]))
                    print(f"Партия окончена: {outcome.value}")
                    return
                continue

            raw = input("Твой ход (h8 / u / q): ")
            if raw.strip().lower() == "q":
                return
            if raw.strip().lower() == "u":
                try:
                    moves = undo_truncate(moves=moves, for_color=human)
                except DomainError as e:
                    print(f"Undo нельзя: {e}")
                continue
            point = parse_input(raw)
            if point is None:
                print("Не понял. Пример: h8")
                continue
            try:
                moves = apply_move(moves, point, forbidden=forbidden)
            except DomainError as e:
                print(f"Ход отвергнут: {e}")
                continue
            outcome = outcome_after(moves)
            if outcome is not None:
                print(render_board(moves=moves, forbidden=[]))
                print(f"Партия окончена: {outcome.value}")
                return
    finally:
        await adapter.close()
```
Ключевые отличия от текущего: `forbidden` считается **безусловно** из позиции в начале каждого полухода (убран гейт `if human is Color.BLACK else []`); доска печатается **каждый полуход**, включая ход движка (фолы чёрного-движка видны белому-человеку); `forbidden` отдаётся в `apply_move` **и движку** (стр. с `engine_pt`), не только человеку — валидация единообразна.

- [ ] **Step 2: Прогнать существующие юниты — без регрессий**

Run: `uv run pytest tests/unit/test_play_cli.py -v` и `uv run pytest -q`
Expected: PASS (render_board/parse_input не менялись; game_loop юнитами не покрыт — проверяется smoke).

- [ ] **Step 3: Линт**

```bash
uv run ruff check app tests scripts && uv run ruff format app tests scripts
```
Expected: clean.

- [ ] **Step 4: Ручной smoke (Alexey, шаг 10) — НЕ автоматизировать**

`uv run python -m scripts.play_cli --level novice`. Проверить: играя **за белых**, на ходу движка-чёрного видны фолы `×` (раньше не показывались); играя за чёрных — как и было; ход вне фола/зоны отвергается. (Запускает Alexey; реализатор интерактивный CLI не гоняет.)

- [ ] **Step 5: Коммит (после одобрения smoke)**

```bash
git add scripts/play_cli.py
git commit -m "fix(cli): фолы и валидация от позиции, не от роли (показ всегда, PvP-ready)"
```

---

## Self-Review (проведено)

- **Покрытие тикета `rj-dxe`:** (1) показ фолов от позиции + рендер каждый полуход — Task 2; (2) единообразная валидация (`forbidden` в `apply_move` и движку) — Task 2; (3) имя `undo_truncate` нейтрально — Task 1. Статус-енумы — в `rj-8sc` (вне этого плана).
- **Типы/имена:** `undo_truncate(*, moves, for_color, preset=1)` согласован между `game.py`, `test_game.py`, `play_cli.py`.
- **Поведение домена не меняется** (Task 1 — чистый rename; тесты остаются зелёными). Task 2 — переустройство проводки play_cli, проверяется ручным smoke + существующим render-тестом.
- **Без placeholder'ов:** код полный.

## Что НЕ в этом этапе (scope — не предлагать как findings)

- Статус-енумы `GameStatus.AWAITING_HUMAN`/`ENGINE_THINKING`, `UndoRejectReason.ENGINE_THINKING` и `check_undo` — переименование нейтрально в `rj-8sc` (статус-машина этапа 2).
- Ветка `human`/движок в драйвере `game_loop` (выбор, чей ввод) — легитимная оркестрация HvE-smoke, не течь.
- Юнит-тесты на интерактивный `game_loop` (DI адаптера, capsys) — не вводим; harness проверяется ручным smoke, как и прежде.
- PvP-семантика undo (что откатывать, когда обе стороны люди) — будущее (этап 2+).
- Веб-фронт показа фолов — этап 4 (там тоже от позиции, заложим отдельно).
