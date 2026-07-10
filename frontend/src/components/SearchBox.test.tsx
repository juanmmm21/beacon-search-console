import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { SearchBox } from "./SearchBox";

vi.mock("../api/client", () => ({
  api: {
    autocomplete: vi.fn(),
    search: vi.fn(),
    indexStats: vi.fn(),
  },
}));

const mockedAutocomplete = vi.mocked(api.autocomplete);

/** `SearchBox` es un input controlado (`value`/`onChange` los da el padre,
 * como hace `App`) — montarlo con un `value` fijo y un `onChange` que no
 * actualiza nada haría que React devolviera el input a ese valor fijo tras
 * cada tecla, así que cada pulsación se vería como si reemplazara todo el
 * contenido anterior en vez de acumularlo. Este wrapper reproduce el mismo
 * patrón controlado que `App.tsx` usa de verdad. */
function ControlledSearchBox({ onChangeSpy }: { onChangeSpy?: (value: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <SearchBox
      value={value}
      onChange={(next) => {
        setValue(next);
        onChangeSpy?.(next);
      }}
    />
  );
}

// Timers reales, no falsos: `userEvent` y los timers falsos de Vitest tienen
// una interacción conocida y frágil (el `type()` interno puede quedarse
// esperando un timer que nunca avanza). El debounce del componente es de
// 150ms, así que esperar en tiempo real con `waitFor`/timeouts generosos es
// más simple y fiable que orquestar timers falsos.
describe("SearchBox autocomplete", () => {
  it("fetches suggestions only after the debounce window, not per keystroke", async () => {
    mockedAutocomplete.mockResolvedValue({
      prefix: "pyt",
      suggestions: [
        { text: "python", score: 139 },
        { text: "python3", score: 5 },
      ],
    });
    const user = userEvent.setup();
    render(<ControlledSearchBox />);

    await user.type(screen.getByRole("combobox"), "pyt");
    expect(mockedAutocomplete).not.toHaveBeenCalled();

    expect(await screen.findByRole("listbox", {}, { timeout: 1000 })).toBeInTheDocument();
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByText("python3")).toBeInTheDocument();
    expect(mockedAutocomplete).toHaveBeenCalledTimes(1);
    expect(mockedAutocomplete).toHaveBeenLastCalledWith("pyt", 8, expect.anything());
  });

  it("does not fetch suggestions for an empty or whitespace-only prefix", async () => {
    const user = userEvent.setup();
    render(<ControlledSearchBox />);

    await user.type(screen.getByRole("combobox"), "   ");
    // Espera más que la ventana de debounce (150ms) en tiempo real: si el
    // componente fuera a llamar a la API, ya lo habría hecho para entonces.
    await new Promise((resolve) => setTimeout(resolve, 250));

    expect(mockedAutocomplete).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("lets ArrowDown + Enter apply the active suggestion and closes the dropdown", async () => {
    mockedAutocomplete.mockResolvedValue({
      prefix: "pyt",
      suggestions: [
        { text: "python", score: 139 },
        { text: "python3", score: 5 },
      ],
    });
    const user = userEvent.setup();
    const onChangeSpy = vi.fn();
    render(<ControlledSearchBox onChangeSpy={onChangeSpy} />);

    await user.type(screen.getByRole("combobox"), "pyt");
    await screen.findByRole("listbox", {}, { timeout: 1000 });

    await user.keyboard("{ArrowDown}{Enter}");

    expect(onChangeSpy).toHaveBeenLastCalledWith("python");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("wraps ArrowUp navigation from the first suggestion back to the last", async () => {
    mockedAutocomplete.mockResolvedValue({
      prefix: "pyt",
      suggestions: [
        { text: "python", score: 139 },
        { text: "python3", score: 5 },
      ],
    });
    const user = userEvent.setup();
    const onChangeSpy = vi.fn();
    render(<ControlledSearchBox onChangeSpy={onChangeSpy} />);

    await user.type(screen.getByRole("combobox"), "pyt");
    await screen.findByRole("listbox", {}, { timeout: 1000 });

    // ArrowDown una vez lleva al índice 0 ("python"); ArrowUp desde ahí debe
    // envolver al último elemento ("python3"), no quedarse fuera de rango.
    await user.keyboard("{ArrowDown}{ArrowUp}{Enter}");

    expect(onChangeSpy).toHaveBeenLastCalledWith("python3");
  });

  it("closes the dropdown without throwing when the autocomplete request fails", async () => {
    mockedAutocomplete.mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();
    render(<ControlledSearchBox />);

    await user.type(screen.getByRole("combobox"), "pyt");

    await waitFor(() => expect(mockedAutocomplete).toHaveBeenCalledTimes(1), { timeout: 1000 });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("shows the v1 engine-limitation hint next to the input", () => {
    render(<SearchBox value="" onChange={vi.fn()} />);

    expect(screen.getByText(/solo/)).toBeInTheDocument();
    expect(screen.getByText("site:")).toBeInTheDocument();
  });
});
