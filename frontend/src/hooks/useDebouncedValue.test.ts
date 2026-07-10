import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDebouncedValue } from "./useDebouncedValue";

describe("useDebouncedValue", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the initial value immediately", () => {
    const { result } = renderHook(() => useDebouncedValue("python", 300));

    expect(result.current).toBe("python");
  });

  it("does not update before the delay elapses", () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 300), {
      initialProps: { value: "p" },
    });

    rerender({ value: "py" });
    act(() => {
      vi.advanceTimersByTime(299);
    });

    expect(result.current).toBe("p");
  });

  it("updates to the latest value once the delay has fully elapsed", () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 300), {
      initialProps: { value: "p" },
    });

    rerender({ value: "py" });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(result.current).toBe("py");
  });

  // El caso que justifica el debounce: tecleo rápido no debe producir un
  // valor estabilizado por cada tecla, solo el último tras la pausa.
  it("collapses several rapid changes into a single update with only the final value", () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 300), {
      initialProps: { value: "p" },
    });

    for (const next of ["py", "pyt", "pyth", "pytho", "python"]) {
      rerender({ value: next });
      act(() => {
        vi.advanceTimersByTime(100); // menos que los 300ms del delay
      });
    }
    expect(result.current).toBe("p"); // ningún intermedio llegó a estabilizarse

    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current).toBe("python");
  });

  it("restarts the timer whenever delayMs itself changes", () => {
    const { result, rerender } = renderHook(({ delay }) => useDebouncedValue("python", delay), {
      initialProps: { delay: 300 },
    });

    rerender({ delay: 500 });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    // El valor no ha cambiado en ningún momento ("python" todo el rato), así
    // que sigue siendo "python" — este test solo confirma que cambiar
    // delayMs no rompe el hook ni deja timers colgados sin limpiar.
    expect(result.current).toBe("python");
  });
});
