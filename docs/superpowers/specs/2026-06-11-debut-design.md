# Дебют RIF Уровень 1 — дизайн

- **Дата:** 2026-06-11
- **Статус:** черновик на ревью
- **bd:** rj-6vh (Дебют-база RIF Уровень 1)
- **Дополняет:** основную спеку §4.10 (полная процедура RIF) и §4.9 (изоляция слоёв)

## Проблема

Наивная реализация дебюта завязывается на «человек против компьютера»: правило
дебюта кодируется дважды — как валидация-отказ для хода человека и как «костыль»
(`YXBLOCK`) для хода движка, а решение «ограничить ход зоной» размазано по
вызывающему коду с ветвлением `if человек / else движок`. Это даёт три болезни:

- **завязка на роль** — правило игры названо и устроено через «кто ходит»;
- **неверные имена** — `validate_human_move` / `human_color`: легальность хода (на
  доске · свободна · не фол для чёрных · в дебютной зоне) не зависит от того,
  человек ходит или ИИ;
- **тесносвязность** — склейка `opening_zone ↔ адаптер ↔ валидация` живёт в
  caller'е, без фасада.

Дебют — это **правило позиции**: какие клетки легальны на ходу № N. Кто этот ход
делает (человек кликнул / движок посчитал) — отдельный тонкий слой, и он не должен
течь в правила или в механику движка.

## Решение

### Принцип: центр — стартовая позиция, а не ход

По RIF ход 1 чёрных всегда в центр (H8 = `(7,7)`) — выбора нет. Поэтому **партия
рождается с чёрным камнем в центре**: `moves` инициализируется как `[(7,7)]`, далее
ход передаётся той стороне, чья очередь. Это убирает целый класс сложности —
синглтон-кейс, ветку «ставим центр сами», и риск движкового fallback на пустой
доске (см. «Подтверждённый протокол», searchthread.cpp:382). Позиционные
ограничения остаются ровно на двух ходах — оба много-клеточные и оба проверены
живыми прогонами.

Цвет человека по-прежнему случайный (§4.6): если человек белый — он ходит первым
реально (ход 2); если чёрный — первым ходит движок-белый (ход 2). В обоих случаях
центр уже стоит.

### Слои и фасады (изоляция §4.9)

Два фасада, между ними — чистый домен:

1. **Фасад движка** — `RapfiAdapter` (уже есть). Знает протокол/`YXBLOCK` как
   механику, принимает `allowed_zone` нейтрально, про «дебют» не знает.
2. **Фасад хода/партии** — новый сервисный слой `app/game_service.py` (§4.9).
   Прячет оркестрацию и дебютную механику; его дёргают и `play_cli`, и будущий
   HTTP-сервис (этап 2). Снаружи: «применить предложенный ход» и «ход движка для
   позиции» — без знания про дебют и `YXBLOCK`.

Между ними — **чистый домен** (без ролей, без I/O): зона дебюта, правило хода, undo.

### Домен (`app/domain/`)

- **`opening.py` (новый)** — единственный источник правды о дебютной зоне:
  ```python
  def opening_zone(move_count: int) -> frozenset[Point] | None:
      """Дебютная зона для хода № move_count (= len(moves)).
      0 → {(7,7)} (центр; в партии не встречается — центр предзаполнен),
      1 → центральный 3×3 (x,y ∈ 6..8),
      2 → центральный 5×5 (x,y ∈ 5..9),
      ≥3 → None (без ограничений)."""
  ```
  Зона — **чистая геометрия квадрата**, занятость не вычитает (это ортогонально,
  проверяется отдельно). Используется проверкой хода, сервисом (обуздание движка) и
  UI (подсветка) — один источник.

- **`values.py`** — `+OPENING_VIOLATION` в `MoveRejectReason`.

- **`game.py`** — `validate_human_move` **переименовать** в нейтральное правило
  хода `validate_move`, разрезав по линии «правило / оркестрация»:
  ```python
  def validate_move(
      *, moves: Sequence[Point], point: Point, forbidden: Sequence[Point]
  ) -> None:
      """Бросает MoveRejected, если ход недопустим по ПРАВИЛАМ (не по статусу/очереди).
      Порядок: геометрия → занятость → дебютная зона → фол.
      Сторона-на-ходу выводится из len(moves); роль (человек/ИИ) не нужна."""
  ```
  - убираем параметр `human_color`; фол применяется к стороне-на-ходу:
    `color_of_move(len(moves)) is Color.BLACK and point in forbidden`;
  - проверки **статуса партии** (`GAME_FINISHED`) и **очереди** (`NOT_YOUR_TURN`)
    **уезжают в сервис** (`apply_move`) — это оркестрация, не правило хода;
  - новая проверка дебюта между занятостью и фолом:
    `zone = opening_zone(len(moves)); if zone is not None and point not in zone: raise MoveRejected(OPENING_VIOLATION)`.

- **`game.py`** — `undo_truncate` живёт здесь (рядом с правилом хода;
  `app/domain/undo.py` — это `UndoPolicy`/`check_undo`, другая сущность, её не
  трогаем). Добавляем **дно** (preset-камни неубираемы): иначе откат человека-чёрного
  снимет центр — для чёрного очередь при чётной длине, и с позиции `[center, white]`
  (len=2) текущий код спускается к `k=0` (пустая доска). Floor — `k` не ниже `preset`
  (=1, центр):
  ```python
  def undo_truncate(*, moves, human_color, preset: int = 1) -> list[Point]:
      ...
      while k >= preset and k % 2 != target_parity:
          k -= 1
      if k < preset:
          raise UndoRejected(UndoRejectReason.NOTHING_TO_UNDO)
      return list(moves[:k])
  ```
  «Дно» для белого — `[center]` (len=1), для чёрного — `[center, white]` (len=2). С
  дефолтом `preset=1` из существующих undo-тестов меняется **ровно один** —
  `test_undo_black_human_removes_engine_and_own_move` (`[center, white]`, ход чёрного):
  было `== []`, станет `NOTHING_TO_UNDO` (чёрный ещё не делал реального хода — центр
  это старт, а не его ход). Остальные undo-тесты проходят без изменений (проверено).
  `preset` — параметр (дефолт 1), чтобы домен не хардкодил старт; знание стартовой
  позиции даёт caller.

### Адаптер движка (`app/rapfi/`)

- **`protocol.py`** — новая чистая функция сборки блок-команд:
  ```python
  def block_commands(block_points: Sequence[Point]) -> list[str]:
      """YXBLOCK-блок: ['YXBLOCK', 'x,y', ..., 'DONE'] для непустого списка, иначе []."""
  ```
  Формат снят с источника (`gomocup.cpp:getBlock`): многострочный, как `BOARD`, но
  без `,who` — `x,y` через запятую до `DONE` (см. «Подтверждённый протокол»).
  `_validate_moves`-стиль анти-инъекции (§5.2) распространить и сюда: в stdin уходят
  только int 0..14.

- **`adapter.py`** — `compute_move` получает опциональный
  `allowed_zone: frozenset[Point] | None`:
  ```python
  async def compute_move(
      self, moves: Sequence[Point], params: EngineParams,
      allowed_zone: frozenset[Point] | None = None,
  ) -> Point:
  ```
  Когда зона задана — блокируем **свободные клетки вне неё**:
  `block = [p for all-board-cells if p not in allowed_zone and p not in set(moves)]`,
  и собираем команды так (блок — **парный**, живёт только внутри этого запроса):
  ```
  init_commands(params)            # START / INFO …
  + block_commands(block)          # YXBLOCK … DONE   (только если зона задана)
  + position_commands(moves)       # BOARD … DONE  (триггерит think)
  + (["YXBLOCKRESET"] if zone else [])   # снимаем тем же запросом, хвостом
  ```
  `YXBLOCKRESET` уходит последней строкой того же `send`: движок читает stdin
  последовательно (посчитал ход → напечатал → прочитал reset → очистил `blockMoves`)
  — гарантированно до следующего `START`. Обычные ходы блок-команд не содержат и
  ничего не наследуют; глобального блок-состояния в адаптере нет. Read-loop `_attempt`
  не меняется (YXBLOCK/YXBLOCKRESET на успехе ничего не печатают). Адаптер про
  «дебют» не знает — изоляция §4.9 цела.

  Контракт: `allowed_zone` — `None` или **много-клеточная** зона. Пустой набор не
  передаётся: caller шлёт только `opening_zone(1)`/`opening_zone(2)` (3×3/5×5, обе
  заведомо со свободными клетками). Пустой `allowed_zone` → `ValueError` — чисто
  программерская страховка, не игровой путь (пустая зона дала бы блок всех свободных
  клеток → пустой `rootMoves` → вырожденное поведение движка).

### Сервис — фасад хода/партии (`app/game_service.py`, новый)

Тонкая оркестрация поверх домена и адаптера. В этапе 1 — один модуль (на этапе 2
дозреет до полноценного game-service с БД). Функции:

- `new_game()` — стартовая позиция партии: `moves = [(7, 7)]`. (Назначение цвета
  человека — случайный выбор — остаётся в caller'е/будущем сервисе сессии; здесь —
  только позиция, чтобы домен и сервис не зависели от роли.)
- `apply_move(moves, point, *, forbidden) -> list[Point]` — **оркестрация +
  правило**: если партия уже завершена (`outcome_after(moves) is not None`, домен
  `rules.py`) → `MoveRejected(GAME_FINISHED)`; иначе зовёт доменное
  `validate_move(moves=moves, point=point, forbidden=forbidden)` и возвращает
  `[*moves, point]`. (`outcome_after -> GameStatus | None` — финал считает домен, не
  передаём флагом. `NOT_YOUR_TURN`/очередь — см. Открытые вопросы.)
- `engine_move(adapter, moves, params) -> Point` — **прячет дебют**:
  `zone = opening_zone(len(moves)); return await adapter.compute_move(moves, params,
  allowed_zone=zone)`. Снаружи — «ход движка для позиции», `YXBLOCK`/зона спрятаны.

Сервис **не** дублирует домен: правило (`validate_move`, `opening_zone`,
`outcome_after`) живёт в домене; сервис только координирует и прячет I/O-механику.

### play_cli (driver, адаптация)

Дёргает сервис, не склеивает домен+адаптер вручную. «Человек/комп» остаётся
**только** в одной ветке «откуда брать кандидата хода»:

```python
moves = new_game()                       # [(7,7)] — центр уже стоит
human = random.choice([BLACK, WHITE])
while True:
    if color_to_move(len(moves)) is not human:        # ход делает движок
        pt = await engine_move(adapter, moves, params)  # дебют спрятан
        moves = apply_move(moves, pt, forbidden=[])
    else:                                              # ход человека
        forbidden = await adapter.forbidden_points(moves) if human is BLACK else []
        zone = opening_zone(len(moves))                 # для подсветки
        print(render_board(moves=moves, forbidden=forbidden, zone=zone))
        pt = parse_input(...)
        moves = apply_move(moves, pt, forbidden=forbidden)  # ловит OPENING_VIOLATION
    outcome = outcome_after(moves)
    ...
```

- `render_board` получает опциональную `zone` и подсвечивает разрешённые **свободные**
  клетки символом `+` (когда ход человека и `zone is not None`). Чисто UX, зеркало
  `opening_zone`.
- `undo_truncate(..., preset=1)` — центр неубираем.

### Lifecycle хода движка в дебюте (последовательность)

Пример: позиция `[(7,7)]` (центр), ход движка-белого (ход 2), зона 3×3:
```
START 15
INFO rule 4
INFO strength N
INFO timeout_turn T
YXBLOCK
<все свободные клетки вне 3×3>,  по строке "x,y"
DONE
BOARD
7,7,2            # центр — камень соперника (who=2 относительно белых)
DONE             # триггерит think → движок печатает "x,y" внутри 3×3
YXBLOCKRESET     # хвостом: чистит blockMoves до следующего запроса
```

## Подтверждённый протокол (выписки из исходника движка)

Сверено с `engine/rapfi/Rapfi/` (Rapfi 0.43.02), `coord_conversion_mode="none"`:

- **Формат `YXBLOCK`** (`command/gomocup.cpp:getBlock`, стр. 691): читает строки
  `x,y` (через запятую) до `DONE`; как `BOARD`, но без поля `who`. Дедуп внутри.
  Успех ничего не печатает.
- **`YXBLOCKRESET`** (стр. 1322): `options.blockMoves.clear()` — чистит весь список,
  тоже молча.
- **`START` НЕ чистит блок**: `start`→`restart`→`board->newGame()` (стр. 561/554)
  не трогает `blockMoves`. Поэтому блок надо снимать **явно** (в нашем дизайне —
  `YXBLOCKRESET` хвостом того же дебютного запроса).
- **Блок никогда не даёт ход вне зоны** (`search/searchthread.cpp:345-393`): даже
  fallback при пустом `rootMoves` (стр. 382) прогоняет кандидатов через **тот же
  фильтр `blockMoves`** (`addMoveToRootMoves`, стр. 345-348) — заблокированную клетку
  движок не выберет ни при каких условиях. Если бы все кандидаты были заблокированы,
  `rootMoves` остался бы пустым (вырожденно), но хода **вне зоны не будет**. В нашем
  дизайне этот вырожденный случай и не достигается: зона (3×3/5×5) всегда содержит
  свободные клетки **внутри candidate-области движка** (`square3_line4` вокруг
  предзаполненного центра, `config.toml`), поэтому `rootMoves` непуст (free-in-zone =
  8 на ходе 2, 23 на ходе 3, проверено живьём).
- **`CheckBoardOK`** (стр. 1270): блок-команды требуют существующей доски (есть
  после `START`) и на успехе output не дают → read-loop адаптера не зашумляют.
- **Блок исключает ходы из корня поиска** (`searchthread.cpp:345`): заблокированные
  клетки не попадают в `rootMoves` → движок выбирает сильнейший ход внутри зоны
  (проверено живьём: ход 2 → внутри 3×3, ход 3 → внутри 5×5).

## Что НЕ в этом этапе (scope — за рамками, не предлагать как findings)

- **Своп цвета и balance-5** (Уровни 2–3, §4.10/§12) — балансировка дебюта. Здесь
  только позиционные ограничения ходов 2–3.
- **Полное выделение статусной машины/оркестрации в отдельный слой** — `apply_move`
  несёт минимум (finished + правило); полноценный game-service со статусами и
  явной проверкой очереди — этап 2 с сервисами/HTTP.
- **HTTP `POST /games` / `POST /moves`, БД-хранение партии** — этапы 2–3. Здесь —
  домен + адаптер + сервис-фасад + `play_cli`.
- **Фронт-блок ввода и подсветка зоны на фронте** — этап 4; в `play_cli` подсветка
  есть как ручной smoke.
- **Калибровка уровней, admin-UI** (rj-tan) — отдельный тикет.

## Затронутый код

- **Создать:** `app/domain/opening.py` (`opening_zone`); `app/game_service.py`
  (`new_game`, `apply_move`, `engine_move`).
- **`app/domain/values.py`** — `+OPENING_VIOLATION` в `MoveRejectReason`.
- **`app/domain/game.py`** — `validate_human_move` → `validate_move` (убрать
  `human_color`, вынести `GAME_FINISHED`/`NOT_YOUR_TURN` в сервис, добавить
  дебютную проверку).
- **`app/domain/game.py`** — `undo_truncate` получает параметр `preset` (floor).
  (`app/domain/undo.py` — `UndoPolicy`/`check_undo`, не трогаем.)
- **`app/rapfi/protocol.py`** — `block_commands`; анти-инъекция на блок-точках.
- **`app/rapfi/adapter.py`** — `compute_move(..., allowed_zone=None)`; сборка
  парного `YXBLOCK … YXBLOCKRESET`.
- **`backend/scripts/play_cli.py`** — через сервис-фасад; `render_board(zone=…)`
  подсветка; `undo_truncate(preset=1)`.
- **Тесты:**
  - `tests/unit/test_opening.py` (новый) — `opening_zone`: ходы 0/1/2/≥3, границы
    3×3 (6..8) и 5×5 (5..9), размеры наборов.
  - `tests/unit/test_game.py` (правка) — `validate_human_move` → `validate_move`
    (новая сигнатура без `status`/`human_color`): остаются геометрия, занятость, фол
    (сторона из позиции). **Новые кейсы:** `OPENING_VIOLATION` (ход вне зоны на ходах
    1/2); «клик в занятый центр в дебюте → `OCCUPIED`, не `OPENING_VIOLATION`»
    (фиксирует порядок: занятость раньше зоны). **undo под preset-модель:**
    `test_undo_black_human_removes_engine_and_own_move` меняет assert `== []` →
    `raises NOTHING_TO_UNDO` (позиция `[center, white]`, чёрный ещё не ходил);
    остальные 5 undo-тестов без изменений. **Сторож очереди:**
    `test_not_your_turn_rejected_by_color` и `test_engine_thinking_rejected`
    **закомментировать** (не удалять) с маркером `# rj-8sc — статус-машина этапа 2` —
    кейсы сохраняются для возврата; `test_finished_game_rejected` → переезжает в
    `test_game_service` (`GAME_FINISHED` через `outcome_after`).
  - `tests/unit/test_protocol.py` (правка) — `block_commands` формат (`YXBLOCK …
    DONE`, пустой список → `[]`) + анти-инъекция точек (`_validate_moves`-стиль).
  - `tests/unit/test_play_cli.py` (правка) — `render_board(zone=…)` подсвечивает
    свободные клетки зоны (`+`); существующий `test_render_board_smoke` не ломается
    (параметр опционален).
  - `tests/unit/test_game_service.py` (новый) — `apply_move` (валидный / занятость /
    `OPENING_VIOLATION` / `GAME_FINISHED` — **на реально завершённой позиции** (напр.
    пять чёрных в ряд): `apply_move` выводит финал из `outcome_after`, поэтому НЕ
    копировать старый 2-камневый фикстур с инжектом статуса — иначе ложно-зелёный
    тест); `engine_move` на фейковом адаптере (в `compute_move` уходит
    `allowed_zone == opening_zone(len(moves))`).
  - `tests/integration/test_adapter.py` (правка) — `compute_move(..., allowed_zone=…)`
    против живого движка: с позиции `[center]` ход внутри 3×3, с `[center, white]`
    ход внутри 5×5; существующие вызовы `compute_move(moves, FAST)` не ломаются
    (новый параметр опционален).
  - `tests/unit/test_undo.py` — **не трогаем** (`UndoPolicy`/`check_undo`).
- **Синхронизировать** основную спеку §4.10 (центр как стартовая позиция; имена
  `validate_move`/сервис-фасад; парный `YXBLOCK`/`YXBLOCKRESET`).

## Открытые вопросы

- **Назначение цвета человека** (random) — сейчас в `play_cli`. На этапе 2 переедет
  в сервис создания сессии; здесь намеренно НЕ кладём в `new_game()`, чтобы и домен,
  и `game_service` оставались независимыми от роли.
- **`NOT_YOUR_TURN` / `ENGINE_THINKING` снимаются с доменного правила** — они
  зависели от параметров `status`/`human_color`, которые мы убираем из `validate_move`.
  `GAME_FINISHED` сохраняется (в `apply_move` через `outcome_after`). Очередь в
  `play_cli` гарантирована структурой цикла (эти сторожа и сейчас в play_cli не
  срабатывают — он всегда валидирует в свою очередь с `AWAITING_HUMAN`); полноценная
  статус-машина (`AWAITING_HUMAN` / `ENGINE_THINKING`) и явная проверка очереди —
  этап 2 с сервисами/HTTP, где ход приходит извне. Решение принято (Alexey, 2026-06-11):
  снятие принимается, два теста **закомментированы** с маркером, требование вернуть
  проверку очереди и тесты зафиксировано тикетом **rj-8sc** (depends on rj-a4k).
