// Registra los matchers de jest-dom (`toBeInTheDocument`, `toHaveTextContent`...)
// sobre el `expect` de Vitest. Vive bajo `src/` (no en la raíz del proyecto)
// a propósito: `tsconfig.json` solo incluye `src/`, y la augmentación de tipos
// de este import solo se aplica al type-checking si el archivo forma parte del
// programa que `tsc -b` compila.
import { cleanup } from "@testing-library/react";
import { toHaveNoViolations } from "jest-axe";
import { afterEach, expect } from "vitest";

import "@testing-library/jest-dom/vitest";
import "./jest-axe.d.ts";

// Sin `test.globals: true` en vitest.config.ts (a propósito: los tests
// importan sus funciones explícitamente de "vitest" en vez de depender de
// globals implícitos), @testing-library/react no detecta un framework de
// test y no registra su auto-cleanup — hay que desmontar cada árbol
// renderizado explícitamente, o el DOM de un test se queda montado y
// contamina las queries del siguiente test del mismo archivo.
afterEach(() => {
  cleanup();
});

// `jest-axe` no es específico de Jest pese al nombre: es axe-core más un
// matcher (`toHaveNoViolations`) escrito contra la API estándar de
// `expect.extend`, que el `expect` de Vitest también implementa — no hace
// falta `vitest-axe` (a fecha de hoy solo publica versiones `pre-release`)
// para tener tests de accesibilidad reales sobre el árbol renderizado.
expect.extend(toHaveNoViolations);
