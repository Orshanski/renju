# Визуальная консистентность фронта (rj-zw5) — План реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Свести все экраны фронта к эталону `prototype/index.html` (единая рамка 1120px + узкий контент внутри, единый заголовочный блок eyebrow/title/sub, красный eyebrow с тире везде) + зарезервировать место под скроллбар, вынеся канонические стили в один общий слой, чтобы экраны не разъезжались снова.

**Architecture:** Общий слой — **CSS Modules `composes`**, НЕ React-компонент. Создаём `src/styles/layout.module.css` с каноническими классами `wrap`/`eyebrow`/`title`/`sub`; каждый экранный модуль подтягивает их через `composes: … from "../styles/layout.module.css"`, добавляя лишь свою специфику (узкие под-блоки, пер-экранные margin). Структура JSX и тексты не меняются → тесты (getByRole/getByText) не затрагиваются. Источник визуала становится единственным → дрейф структурно невозможен.

**Tech Stack:** React 19, TypeScript, Vite 6, CSS Modules + @value-токены (`src/styles/tokens.module.css`), Vitest.

## Global Constraints

- Источник истины — `prototype/index.html`. Все значения берём из него, не изобретаем. Спека: `docs/superpowers/specs/2026-06-17-visual-consistency-design.md`.
- Команды из `frontend/`. Ветка — `feat/rj-zw5-visual` (НЕ main).
- **Подход к проверке (важно — это не обычный TDD):** CSS-вёрстка (ширины/цвета/раскладка) в jsdom **не вычисляется** — юнит-тестами на пиксели её проверить нельзя. Поэтому:
  - регрессионный гард каждого шага = `npx tsc --noEmit` (0 ошибок) + `npx vitest run` (ВСЕ зелёные, ничего не сломано);
  - корректность CSL-значений сверяется ревьюером по диффу против прототипа;
  - финальный гейт — **визуальная приёмка Alexey** (последний шаг). Новых юнит-тестов на CSS не пишем (нечего «красить» в jsdom) — это осознанно, а не пропуск дисциплины.
- Тексты заголовков/контента НЕ трогаем (они уже совпадают с мокапом).
- НЕ редизайн: визуальный язык/палитра/шрифты/компоновку не меняем, только приводим к прототипу. Логику/поведение/контент не трогаем. `bpCompact` сохраняем. Бэкенд/движок — вне задачи.
- **Login НЕ трогаем** — отдельная fixed-сцена (`LoginPage.module.css` `.stage`), единой рамки не касается.
- Канонические значения (из прототипа): `.wrap` max-width **1120px**, margin `0 auto`; `.eyebrow` — `fontSerif`, weight 600, letter-spacing 5px, uppercase, **font-size 11px**, `color: vermillion`, `display:flex; align-items:center; gap:10px`, `::before { content:""; width:26px; height:1px; background: vermillion; display:inline-block }`; `.title` — `fontSerif`, weight 800, **font-size 40px**, line-height 1.05, letter-spacing -0.5px; `.sub` — `color: sumiSoft`, font-size 15px, weight 300.

---

### Task 1: Общий слой `layout.module.css` + scrollbar-gutter + миграция эталонного экрана (HomePage)

**Files:**
- Create: `frontend/src/styles/layout.module.css`
- Modify: `frontend/src/styles/reset.css`
- Modify: `frontend/src/pages/HomePage.module.css`

**Interfaces (Produces):** классы `wrap`, `eyebrow`, `title`, `sub` в `layout.module.css`, импортируемые через `composes`. Остальные задачи их потребляют.

- [ ] **Step 1: Создать `layout.module.css`** с каноническими классами (значения — из Global Constraints, токены — из `tokens.module.css`):

```css
/* Общий слой раскладки/типографики — единый источник по prototype/index.html.
   Потребители подтягивают классы через composes, добавляя свою специфику. */
@value vermillion, sumiSoft, fontSerif from "./tokens.module.css";

.wrap { max-width: 1120px; margin: 0 auto; }

.eyebrow {
  font-family: fontSerif;
  font-weight: 600;
  letter-spacing: 5px;
  text-transform: uppercase;
  font-size: 11px;
  color: vermillion;
  display: flex;
  align-items: center;
  gap: 10px;
}
.eyebrow::before { content: ""; width: 26px; height: 1px; background: vermillion; display: inline-block; }

.title {
  font-family: fontSerif;
  font-weight: 800;
  font-size: 40px;
  line-height: 1.05;
  letter-spacing: -0.5px;
}

.sub { color: sumiSoft; font-size: 15px; font-weight: 300; }
```

- [ ] **Step 2: scrollbar-gutter в `reset.css`** — добавить резерв места под полосу прокрутки на корневой скролл-контейнер (`html`):

```css
* { box-sizing: border-box; margin: 0; padding: 0; }
html { scrollbar-gutter: stable; }
html, body, #root { height: 100%; }
body { -webkit-font-smoothing: antialiased; }
```

- [ ] **Step 3: Мигрировать HomePage на общий слой** (эталон-проверка: HomePage уже визуально совпадает с прототипом, после миграции должна выглядеть так же). В `HomePage.module.css` заменить локальные определения на `composes`, сохранив пер-экранную специфику (`.head` flex, `.title` margin):

```css
.wrap { composes: wrap from "../styles/layout.module.css"; }
/* .head, .newBtn, .tabs и пр. — без изменений */
.eyebrow { composes: eyebrow from "../styles/layout.module.css"; }
.title { composes: title from "../styles/layout.module.css"; margin: 14px 0 6px; }
.sub { composes: sub from "../styles/layout.module.css"; }
```
Удалить старые свойства `.eyebrow`/`.title`/`.sub`/`.wrap`, которые теперь приходят из общего слоя (оставить только пер-экранные: margin у title, всё про `.head`/`.tabs`/`.newBtn`). Текст/JSX `HomePage.tsx` НЕ трогать.

- [ ] **Step 4: Проверка** — `cd frontend && npx tsc --noEmit && npx vitest run`. Ожидание: 0 ошибок типов; все тесты зелёные (HomePage.test и пр. не затронуты — JSX не менялся). Запустить `npx vite build` — сборка успешна (composes резолвится).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles/layout.module.css frontend/src/styles/reset.css frontend/src/pages/HomePage.module.css
git commit -m "feat(rj-zw5): общий слой layout.module.css (wrap/eyebrow/title/sub) + scrollbar-gutter; HomePage на него"
```

---

### Task 2: NewGamePage + GamePage на общий слой

**Files:**
- Modify: `frontend/src/pages/NewGamePage.module.css`
- Modify: `frontend/src/pages/GamePage.module.css`

**Interfaces (Consumes):** `wrap`/`eyebrow`/`title`/`sub` из Task 1.

Оба экрана уже визуально эталонные — это чистая дедупликация на общий слой, вид не меняется.

- [ ] **Step 1: NewGamePage** — `composes`, сохранив **margin title 22px снизу** (пробел до плиток уровней — пер-экранный, НЕ из общего слоя):

```css
.wrap { composes: wrap from "../styles/layout.module.css"; }
.eyebrow { composes: eyebrow from "../styles/layout.module.css"; }
.title { composes: title from "../styles/layout.module.css"; margin: 14px 0 22px; }
.sub { composes: sub from "../styles/layout.module.css"; }
```
Удалить старые дублирующие свойства этих классов; остальное (`.levels`/`.lvl`/`.dice` и пр.) — без изменений.

- [ ] **Step 2: GamePage** — у Game нет `.title`; есть `.wrap` и верхний `.eyebrow` («Партия · ты играешь…», уже эталонный) + внутрикарточный `.eyebrow` («Лог ходов»). `.wrap` и `.eyebrow` → `composes`, сохранив пер-экранный `margin-bottom: 18px` у верхнего eyebrow и `.card .eyebrow { margin-bottom: 10px }` для внутрикарточного:

```css
.wrap { composes: wrap from "../styles/layout.module.css"; }
.eyebrow { composes: eyebrow from "../styles/layout.module.css"; margin-bottom: 18px; }
/* .card .eyebrow { margin-bottom: 10px; } — оставить как есть (специфика внутрикарточного) */
```
Удалить старые дублирующие свойства `.eyebrow`/`.wrap`. JSX не трогать.

- [ ] **Step 3: Проверка** — `cd frontend && npx tsc --noEmit && npx vitest run`. 0 ошибок; все тесты (включая GamePage.test, useGame и пр.) зелёные.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/NewGamePage.module.css frontend/src/pages/GamePage.module.css
git commit -m "feat(rj-zw5): NewGamePage + GamePage на общий слой (вид без изменений)"
```

---

### Task 3: SettingsPage — рамка 1120 + красный eyebrow + title 40px, контент узкий внутри

**Files:**
- Modify: `frontend/src/pages/SettingsPage.module.css`

**Interfaces (Consumes):** `wrap`/`eyebrow`/`title`/`sub` из Task 1.

Сейчас (сверено): `.wrap` 680, `.eyebrow` серый/fontSans/2px/без тире, `.title` 28px, `.sectionTitle` серый. Цель — рамка 1120, eyebrow/title по эталону, форма 680 внутри.

- [ ] **Step 1: Рамка и заголовочный блок** в `SettingsPage.module.css`:

```css
.wrap { composes: wrap from "../styles/layout.module.css"; padding: 0 0 48px; }
.eyebrow { composes: eyebrow from "../styles/layout.module.css"; }
.title { composes: title from "../styles/layout.module.css"; margin: 0 0 28px; }
```
Удалить старые серые определения `.eyebrow` (fontSans/sumiFaint/2px) и `.title` (28px). `.wrap` теряет `max-width:680`, получает 1120 из общего слоя, сохраняет свой `padding`.

- [ ] **Step 2: Узкий контент внутри рамки** — `.settings { max-width: 680px }` УЖЕ присутствует (`SettingsPage.module.css:36`, без margin:auto → прижата влево, как прототип стр.217). Менять не нужно; после расширения рамки до 1120 именно `.settings` держит форму узкой слева. Просто убедиться, что правка `.wrap` (Step 1) не задела `.settings`.

- [ ] **Step 3: Секционные ярлыки** — `.sectionTitle` (серый, `margin: 30px 0 14px`, стр.27-34) → красный eyebrow через `composes`, с детерминированной обработкой двойного зазора перед блоком пароля:

```css
.sectionTitle { composes: eyebrow from "../styles/layout.module.css"; margin: 30px 0 14px; }
.passwordBlock .sectionTitle { margin-top: 0; }
```
Удалить старые серые свойства `.sectionTitle` (fontSans/sumiFaint/letter-spacing 2px — придут красные из общего слоя). JSX `SettingsPage.tsx` не трогаем — класс остаётся `styles.sectionTitle` на всех трёх секциях.

**Обоснование (документируем, чтобы не наступить снова):** в прототипе у секций разные инлайн-margin сверху — «Откаты» 24px (стр.404), «Управление партиями» 30px (стр.421), «Сменить пароль» — без своего top-margin (верх даёт обёртка `.passwordBlock { margin-top:30px }`, стр.438/`SettingsPage.module.css:182-185`). Поскольку JSX переиспользует один класс `.sectionTitle` на всех трёх (не трогаем JSX), берём единый `30px 0 14px` — «Откаты» получат 30px вместо 24px (осознанный ±6px, единый вертикальный ритм). Для «Сменить пароль» добавляем `.passwordBlock .sectionTitle { margin-top: 0 }`: верхний отступ задаёт сам `.passwordBlock` (30px), ярлык внутри его НЕ добавляет — это исключает риск двойного зазора (30+30) независимо от схлопывания margin (после `composes` ярлык становится `display:flex` — поведение схлопывания делается недетерминированным, поэтому гасим явно). `.passwordBlock { margin-top:30px; max-width:440px }` (стр.182-185) НЕ трогаем.

- [ ] **Step 4: `.passwordBlock` НЕ трогаем** — `{ margin-top: 30px; max-width: 440px }` (стр.182-185) остаётся как есть; внутри него меняется только `.sectionTitle` (Step 3).

- [ ] **Step 5: Проверка** — `cd frontend && npx tsc --noEmit && npx vitest run`. 0 ошибок; `SettingsPage.test.tsx` (9 тестов, getByRole/getByText) зелёные — JSX не менялся.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SettingsPage.module.css
git commit -m "feat(rj-zw5): SettingsPage — рамка 1120 + красный eyebrow с тире + title 40px, форма 680 внутри"
```

---

### Task 4: AdminPage + EngineTab — рамка 1120 + красный eyebrow + title 40px; вернуть внутренние ширины движка

**Files:**
- Modify: `frontend/src/admin/AdminPage.module.css`
- Modify: `frontend/src/admin/EngineTab.module.css`

**Interfaces (Consumes):** `wrap`/`eyebrow`/`title` из Task 1.

Сейчас (сверено): Admin `.wrap` 860, `.eyebrow` серый/fontSans/2px/без тире, `.title` 28px. EngineTab `.sub`/`.tbl`/`.setrow` без max-width (держались рамкой 860).

- [ ] **Step 1: AdminPage рамка + заголовок** в `AdminPage.module.css`:

```css
.wrap { composes: wrap from "../styles/layout.module.css"; }
.eyebrow { composes: eyebrow from "../styles/layout.module.css"; }
.title { composes: title from "../styles/layout.module.css"; margin: 0 0 28px; }
```
Удалить старые серые `.eyebrow` (стр.9-16) и `.title` 28px (стр.18-24). `.tabs`/`.active`/`.stub` — без изменений (вкладки/стаб остаются как есть).

- [ ] **Step 2: EngineTab — вернуть внутренние max-width по прототипу** (иначе вкладка «Движок» растянется во всю рамку 1120):

```css
.sub { /* …существующие свойства… */ max-width: 640px; }     /* прототип стр.468 */
.tbl { /* …существующие (width:100%)… */ max-width: 540px; }  /* прототип стр.469 */
.setrow { /* …существующие… */ max-width: 540px; }            /* прототип стр.481 (NNUE) */
```
Добавить `max-width` к существующим правилам `.sub` (стр.4-10), `.tbl` (стр.12-18), `.setrow` (стр.55-62), НЕ удаляя прочих свойств.

- [ ] **Step 3: UsersTab — без изменений** — таблица `.tbl { width:100% }` (`UsersTab.module.css:36`) остаётся полноширинной (в прототипе у таблицы пользователей нет max-width — намеренно широкая в рамке 1120). Проверить, что её НЕ задели.

- [ ] **Step 4: Проверка** — `cd frontend && npx tsc --noEmit && npx vitest run`. 0 ошибок; `AdminPage.test.tsx`, `UsersTab.test.tsx`, `EngineTab.test.tsx` (если есть) зелёные.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/admin/AdminPage.module.css frontend/src/admin/EngineTab.module.css
git commit -m "feat(rj-zw5): AdminPage — рамка 1120 + красный eyebrow + title 40px; EngineTab вернул внутренние max-width"
```

---

### Task 5: Финальная проверка адаптива + визуальная приёмка

**Files:** (правок кода не предполагается; при находках — точечный фикс в соответствующем модуле)

- [ ] **Step 1: Полный прогон** — `cd frontend && npx tsc --noEmit && npx vitest run && npx vite build`. Всё зелёное, сборка успешна, `dist/` собран.

- [ ] **Step 2: Проверка bpCompact (≤900px)** — у админки/настроек своего `@media` нет (отступы даёт `Shell .main`). Убедиться (через сборку/локальный просмотр), что после расширения рамки до 1120 таблица «Движок» и контент на узком экране не дают горизонтального переполнения (внутренние max-width 540/640 этому помогают). При переполнении — добавить точечный фикс (напр. `overflow-x:auto` на таблице) в EngineTab.

- [ ] **Step 3: Визуальная приёмка — Alexey (гейт):**
  - переключение между всеми экранами (Доска / Новая партия / Игра / Настройки / Админка) — без горизонтального и вертикального прыжка;
  - единый левый край заголовков на всех экранах;
  - заголовки одного размера (крупные); eyebrow везде красный с тире (включая Настройки и Админку);
  - формы/таблицы не растянуты во всю рамку (настройки — узкая форма слева, движок — узкая таблица слева, пользователи — широкая);
  - Логин не затронут.
  - Эталон для сверки: `prototype/index.html` (`python3 -m http.server --directory prototype`).

- [ ] **Step 4 (после приёмки): финальный холистик-ревью всей ветки** (свежий независимый ревьюер) перед мержем — диффы всех экранов как интегрированный результат.
