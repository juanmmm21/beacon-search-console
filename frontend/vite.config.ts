import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo, la API FastAPI corre en otro puerto (8000 por defecto);
// el proxy evita CORS y deja al cliente usar rutas relativas `/api/v1/...`.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
