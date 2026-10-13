import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs at 127.0.0.1:8000 (just up); the dev server proxies /v1 so the browser talks to one origin.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/v1": "http://127.0.0.1:8000" } },
});
