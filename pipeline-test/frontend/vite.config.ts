import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5175,
    proxy: {
      // The browser stays on one origin, so no CORS preflight and no internal URL
      // appears in the page. Server-sent events pass through this proxy untouched.
      "/api": { target: "http://localhost:8090", changeOrigin: true },
    },
  },
});
