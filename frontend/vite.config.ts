/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Без dev-сервера: фронт доставляет БЭК (StaticFiles отдаёт собранный dist/). Vite здесь —
  // только бандлер (build) и тест-раннер (test).
  build: {
    outDir: "dist",
    modulePreload: { polyfill: false }, // CSP: убрать inline polyfill-скрипт (цель — современный Safari)
    assetsInlineLimit: 0, // CSP: не инлайнить ассеты
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test/setup.ts"], css: true },
});
