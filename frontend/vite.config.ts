import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo, las APIs FastAPI corren en otros puertos: la consola
// original en 8000 (`/api/v1`) y el buscador de documentación en 8001 (`/v1`,
// `/mcp`); el proxy evita CORS y deja al cliente usar rutas relativas.
// Dos páginas: index.html (consola) y docs.html (buscador de documentación).
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        docs: resolve(__dirname, "docs.html"),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/v1": {
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
      },
    },
  },
});
