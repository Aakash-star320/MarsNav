import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
  server: { port: 5173 },
  build: {
    rollupOptions: {
      input: { app: "index.html", map: "map-preview.html" },
      output: { manualChunks: { three: ["three"], leaflet: ["leaflet"] } },
    },
  },
});
