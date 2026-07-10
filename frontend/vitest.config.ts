import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Config de test separada de vite.config.ts: el proxy de desarrollo a la API
// no tiene sentido bajo jsdom, y mezclarlo solo añade ruido a la config real
// del dev server.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // `clearMocks`, no `mockReset`: limpia el historial de llamadas
    // (`.mock.calls`) entre tests de un mismo archivo sin borrar la
    // implementación (`mockResolvedValue(...)`) que un `beforeEach` de nivel
    // superior haya fijado para todo el `describe` — sin esto, tests
    // consecutivos que comparten el mismo módulo mockeado ven llamadas
    // acumuladas de tests anteriores.
    clearMocks: true,
    restoreMocks: true,
  },
});
