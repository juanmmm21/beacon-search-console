// `@types/jest-axe` solo augmenta el namespace global `jest` y el módulo
// `@jest/expect` — nada de esto llega al `expect` de Vitest (que es su propia
// implementación, compatible en runtime pero con su propio tipo `Assertion`).
// Sin esta augmentación, `expect(results).toHaveNoViolations()` no tipa bajo
// `tsc --strict` aunque funcione en ejecución (el matcher se registra en
// runtime vía `expect.extend(...)` en `setup.ts`).
import "vitest";

declare module "vitest" {
  interface Assertion<T = unknown> {
    toHaveNoViolations(): T;
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void;
  }
}
