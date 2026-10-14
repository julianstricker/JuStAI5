import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const root = fileURLToPath(new URL(".", import.meta.url));
const backend = process.env.JUSTAI_DEV_BACKEND ?? "http://localhost:8080";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": `${root}src` } },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      input: {
        admin: `${root}index.html`,
        display: `${root}display.html`,
      },
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: backend, ws: true, changeOrigin: true },
      "/internal": { target: backend },
    },
  },
  test: { environment: "jsdom" },
});
