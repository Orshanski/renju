# PWA-обвязка (rj-puo)

**Дата:** 2026-06-17
**Статус:** черновик на ревью (v2 — офлайн-поведение в React, не в SW)

## Что делаем

Превращаем фронт в устанавливаемое PWA: иконка на домашнем экране, полноэкранный standalone-режим. Офлайн-поведение — на уровне приложения: хук статуса соединения + аккуратный индикатор «Нет связи», без дёрганья сети. Service worker — минимальный, только для установки и открытия оболочки. Подход подсмотрен в Librarium (`useOnlineStatus` + реакция приложения), но без офлайн-хранилища.

## Что НЕ в этой задаче (scope)

- **Офлайн-игра отсутствует.** Ход уходит к движку на сервере, партия идёт по сети (SSE). Играть офлайн нельзя — сознательно вне scope.
- **SW НЕ кеширует данные** (`/api/*`, SSE) и НЕ делает офлайн-fallback-страниц/навигационных трюков Workbox. Только precache статической оболочки для установки.
- Офлайн-хранилище партий, push-уведомления, background sync — вне scope.

## Архитектура офлайна (ключевое решение)

Офлайн обрабатывается **в React**, а не в service worker:
- `useOnlineStatus()` — хук на `navigator.onLine` + события `online`/`offline`.
- Когда офлайн — приложение показывает индикатор «Нет связи» и не инициирует сетевые действия; когда сеть вернулась — переподключается (у `useGame` уже есть reconnect по `EventSource.onerror`).
- SW нужен лишь чтобы (а) браузер предложил установку, (б) офлайн открылась оболочка приложения (precache `index.html` + ассеты), которая дальше сама покажет «Нет связи».

Это снимает сложность Workbox `navigateFallback`/`offline.html`: навигационный fallback — стандартно на `index.html` (app-shell), а ЧТО показать офлайн решает React.

## Реализация

### `useOnlineStatus` хук

`frontend/src/hooks/useOnlineStatus.ts` (новый) — по образцу Librarium:

```ts
import { useEffect, useState } from "react";

export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    globalThis.addEventListener("online", on);
    globalThis.addEventListener("offline", off);
    return () => {
      globalThis.removeEventListener("online", on);
      globalThis.removeEventListener("offline", off);
    };
  }, []);
  return online;
}
```

### Индикатор «Нет связи» в `Shell`

`frontend/src/components/Shell.tsx` (общая обёртка всех авторизованных экранов: header + `<main><Outlet/></main>`). Добавить под шапкой полоску-баннер, видимую когда `!online`:

```tsx
const online = useOnlineStatus();
// ...
{!online && <div className={styles.offlineBar} role="status">Нет связи — проверьте соединение</div>}
```

Стиль `offlineBar` в `Shell.module.css` — приглушённый предупреждающий (токены `vermillion`/`paper`), не модальный (не блокирует уже загруженный экран). Точный текст/вид — в плане.

### Реакция на офлайн в игре (обязательно)

`frontend/src/game/useGame.ts` реконнектит SSE по `EventSource.onerror`: `es.close()` → таймер → `GET /api/auth/me` → при успехе `connect(cursor)`, при ошибке `return`. **Проблема (ревью):** офлайн `/api/auth/me` бросает сетевую ошибку (не 401) → попадает в `catch` → `return`. Реконнект-цепочка **одноразовая** и обрывается: когда сеть вернётся, `useGame` не подписан на событие `online` и SSE не переподключится — пользователь застрянет на «соперник думает…» с молчащим стримом.

Поэтому интеграция `online`-события в `useGame` **обязательна**: подписаться на `window` `online` и при его наступлении форсировать `connect(viewRef.current?.cursor ?? since)` (если `aliveRef` и нет живого `esRef`). Снять подписку в cleanup.

NB: одноразовость reconnect — возможно существующий дефект `useGame` шире офлайна (один `onerror` → один таймер → `catch/return`, без повтора). В рамках этой задачи закрываем именно офлайн-возврат через событие `online`; если обнаружится, что и обычный обрыв (сервер прилёг) не самовосстанавливается — завести отдельный тикет, не расширять scope PWA молча.

### `vite-plugin-pwa` (минимальный SW)

`frontend/package.json` — `vite-plugin-pwa` в devDependencies.

`frontend/vite.config.ts` — плагин:

```ts
import { VitePWA } from "vite-plugin-pwa";

VitePWA({
  registerType: "autoUpdate",
  injectRegister: null,                 // НЕ инлайнить регистрацию (CSP script-src 'self')
  manifest: {
    id: "/",
    name: "連珠 · Renju",
    short_name: "Renju",
    description: "Профессиональное рэндзю против движка Rapfi",
    lang: "ru",
    theme_color: "#1c1a17",
    background_color: "#f4ecda",
    display: "standalone",
    start_url: "/",
    icons: [
      { src: "pwa-192.png", sizes: "192x192", type: "image/png" },
      { src: "pwa-512.png", sizes: "512x512", type: "image/png" },
      { src: "pwa-512-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  },
  workbox: {
    globPatterns: ["**/*.{js,css,html,svg,png,ico,webmanifest}"],
    navigateFallback: "/index.html",        // app-shell (НЕ offline.html); офлайн открывает оболочку
    navigateFallbackDenylist: [/^\/api\//],  // /api/* и SSE — мимо SW
    // runtimeCaching не задаём: ничего из сети сверх precache не кешируем
  },
})
```

### Регистрация SW — CSP-совместимо

CSP проекта (`backend/app/middleware/security_headers.py`): `script-src 'self'`. Авто-инжект регистрации добавил бы inline-скрипт → нарушение. Поэтому `injectRegister: null` + ручная регистрация в отдельном модуле `frontend/src/pwa.ts` (вынесено из `main.tsx` для тестируемости — иначе тест тянул бы импорт `main.tsx` со всем `App`/роутером):

```ts
// src/pwa.ts
import { registerSW } from "virtual:pwa-register";
export function registerPwa(): void {
  registerSW({ immediate: true });
}
```

`main.tsx` зовёт `registerPwa()` рядом с `createRoot`. Это module из бандла — проходит `script-src 'self'`.

**tsconfig (обязательно):** `import { registerSW } from "virtual:pwa-register"` требует типов плагина. `frontend/tsconfig.json` `compilerOptions.types` сейчас `["vite/client", "vitest/globals", "@testing-library/jest-dom"]` — добавить `"vite-plugin-pwa/client"`. Иначе локальный `tsc --noEmit` (в `npm run build`/typecheck) — красный (CI `npx vite build` без tsc это пропустит, но локально упадёт).

После `vite build` **проверить**, что `dist/index.html` не содержит inline `<script>` без `src` (гарантия CSP).

### Теги в `index.html` (вручную)

`vite-plugin-pwa` инжектит только `<link rel="manifest">`. Остальное добавить руками в `frontend/index.html` `<head>` (всё CSP-нейтральное, не скрипты):

```html
<link rel="apple-touch-icon" href="/apple-touch-icon-180.png" />
<link rel="icon" href="/favicon.ico" sizes="any" />
<meta name="theme-color" content="#1c1a17" />
```

Без `apple-touch-icon` iOS Safari «На экран Домой» не подхватит иконку (iOS игнорирует иконки манифеста).

### Иконки

Исходник — `~/Downloads/image.png` (1254×1254, доска с камнями + печать 連珠). Сгенерировать в `frontend/public/` (Vite копирует `public/*` в корень `dist`):
- `pwa-192.png`, `pwa-512.png`
- `pwa-512-maskable.png` (важные элементы в центральных ~80% — maskable обрезает до squircle)
- `apple-touch-icon-180.png` (180×180)
- `favicon.ico`

Генерация — `sips`/Pillow разово, результат коммитим в `public/`.

### CSP — явные директивы

`backend/app/middleware/security_headers.py`: добавить `manifest-src 'self'; worker-src 'self'`. **Для SW обязательны оба** (зафиксировать, не «просто defense-in-depth»): `worker-src 'self'` — регистрация воркера; `script-src 'self'` (уже есть, НЕ срезать) — исполнение `registerSW`-модуля и `importScripts('workbox-*.js')` внутри SW. Если в будущем `script-src` уведут в nonce-режим — SW сломается. Иконки (`img-src`) наследуют `default-src 'self'` — same-origin .png проходят; `connect-src 'self'` уже покрывает SSE и fetch обновления `sw.js` (same-origin).

### Стык с бэком (StaticFiles + MIME)

`backend/app/app_factory.py` отдаёт `dist/` через StaticFiles + SPA-fallback. `sw.js`, `manifest.webmanifest`, `pwa-*.png`, иконки лежат в корне `dist` → spa-роут отдаёт их как файлы (ветка `candidate.is_file()`), не через fallback. **MIME-проблема:**
- `.webmanifest` не зарегистрирован в Python `mimetypes` → `FileResponse` отдаст `application/octet-stream`.
- `.js` (для `sw.js`/`workbox-*.js`) зависит от системного mime на сервере (Ubuntu) — браузер **откажется регистрировать SW с неверным MIME**.

Фикс: в spa-роуте `app_factory.py` — явный маппинг суффиксов media_type для корневых файлов: `{".webmanifest": "application/manifest+json", ".js": "text/javascript"}`, передавать в `FileResponse(candidate, media_type=...)`. **Только этот вариант** — локальный, тестируемый, не зависит от системного `/etc/mime.types` целевого хоста (глобальный `mimetypes.add_type` мутирует весь процесс и был бы в обход явного контракта роута — не используем). `.png`/`.ico` MIME у Python встроены — их не трогаем. SW scope: `sw.js` в корне → scope `/` (верно).

### Деплой

`.github/workflows/deploy.yml` собирает фронт `npx vite build` — плагин подхватится из конфига, отдельных шагов не нужно. Иконки/манифест из `public/` попадут в `dist`.

## Тесты

- **Фронт (vitest):** `useOnlineStatus` — юнит (offline-событие → false, online → true). Shell — баннер «Нет связи» виден при `navigator.onLine=false` (мок). `registerPwa` (из `src/pwa.ts`) — юнит `pwa.test.ts` с моком `virtual:pwa-register`, проверить что зовёт `registerSW`. Существующие 172 теста — зелёные.
- **Бэк (pytest):** в `test_spa_serving.py` расширить фикстуру `app_with_spa` реальными `sw.js` и `manifest.webmanifest` в `dist`; проверить `GET /sw.js` → `Content-Type: text/javascript` и `GET /manifest.webmanifest` → `application/manifest+json`, оба не `index.html`.
- **Ручная (Alexey):** установка на телефон, standalone-запуск, баннер «Нет связи» при выключенной сети, возврат сети → работа продолжается.

## Порядок реализации

1. `useOnlineStatus` + баннер в `Shell` + тесты (офлайн-поведение в React)
2. Иконки из `image.png` → `public/`; теги в `index.html`
3. `vite-plugin-pwa` + конфиг + `registerSW` в `main.tsx`; проверить отсутствие inline-script в `dist/index.html`
4. CSP `manifest-src`/`worker-src`; MIME в `app_factory.py` + бэк-тест
5. `vite build` локально — проверить генерацию `sw.js`/`manifest`; все тесты зелёные
