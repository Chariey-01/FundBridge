/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// The typed API client lives in ../contracts and is imported directly, so there is one source of
// truth for the API contract. Vite must be allowed to serve files from the repository root.
const repoRoot = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // Dev and preview proxy /api to the Flask backend so the browser stays same-origin (no CORS needed).
  const backend = env.FUNDBRIDGE_BACKEND_URL || "http://127.0.0.1:5000";
  const proxy = { "/api": { target: backend, changeOrigin: false } };
  return {
    plugins: [react()],
    server: { port: 5173, strictPort: true, proxy, fs: { allow: [repoRoot] } },
    preview: { port: 4173, strictPort: true, proxy },
    build: { sourcemap: true },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./tests/setup.ts"],
      include: ["tests/**/*.test.{ts,tsx}"],
      restoreMocks: true,
    },
  };
});
