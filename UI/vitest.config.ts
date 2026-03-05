/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import path from "path";
export default defineConfig({
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./client/src/test/setup.ts"],
    include: ["client/src/**/*.{test,spec}.{js,jsx,ts,tsx}"],
    env: {
      VITE_API_BASE_URL: "http://localhost:8000/api",
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "client/src"),
    },
  },
  define: {
    "import.meta.env": JSON.stringify({
      VITE_API_BASE_URL: "http://localhost:8000/api",
      MODE: "test",
      DEV: false,
      PROD: false,
      SSR: false,
    }),
  },
});
