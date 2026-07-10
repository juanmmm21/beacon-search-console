import { useEffect, useState } from "react";

/** Devuelve `value` estabilizado: solo cambia cuando el valor original lleva
 * `delayMs` sin moverse — la base del "una petición por pausa de tecleo, no
 * por tecla" que exige la caja de búsqueda. */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
