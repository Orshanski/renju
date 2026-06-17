/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: null,
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
        globPatterns: ["**/*.{js,css,html,svg,png,ico,webmanifest,webp}"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//],
      },
    }),
  ],
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
