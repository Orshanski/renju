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
    rollupOptions: {
      output: {
        // модульность бандла: ВЕСЬ вендор (node_modules) отдельным chunk'ом, index — только наш код;
        // экраны грузятся ленивыми chunk'ами по роутам (React.lazy в App.tsx).
        // Функциональная форма: списочная ("react-dom") не цепляет subpath-импорты вида react-dom/client.
        manualChunks: (id) => (id.includes("node_modules") ? "vendor" : undefined),
      },
    },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test/setup.ts"], css: true },
});
