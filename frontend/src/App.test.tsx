import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api/client";
import App from "./App";
import type { SearchResponse } from "./types/api";

vi.mock("./api/client", () => ({
  api: {
    search: vi.fn(),
    autocomplete: vi.fn(),
    indexStats: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    constructor(
      message: string,
      public readonly status: number,
    ) {
      super(message);
      this.name = "ApiError";
    }
  },
}));

const mockedSearch = vi.mocked(api.search);
const mockedAutocomplete = vi.mocked(api.autocomplete);
const mockedIndexStats = vi.mocked(api.indexStats);

function emptySearchResponse(query: string): SearchResponse {
  return {
    query,
    results: [],
    corrections: [],
    shard_statuses: [],
    degraded: false,
    message: null,
  };
}

// Timers reales (ver el comentario equivalente en SearchBox.test.tsx): el
// debounce de búsqueda de App es de 300ms, y `waitFor`/timeouts generosos en
// tiempo real evitan la interacción frágil entre `userEvent` y los timers
// falsos de Vitest.
describe("App", () => {
  beforeEach(() => {
    mockedAutocomplete.mockResolvedValue({ prefix: "", suggestions: [] });
    mockedIndexStats.mockResolvedValue({
      total_documents: 187,
      vocabulary_size: 12422,
      total_postings: 78852,
      average_document_length: 2147.29,
      num_shards: 3,
      last_crawled_at: "2026-07-09T18:59:23.964963+00:00",
    });
    mockedSearch.mockResolvedValue(emptySearchResponse(""));
    // App lee la query inicial de la URL al montar; cada test debe partir limpio.
    window.history.replaceState(null, "", "/");
  });

  // El requisito explícito de la caja de búsqueda: una petición por pausa de
  // tecleo, nunca una por tecla.
  it("debounces search: rapid typing triggers exactly one request with the final query", async () => {
    mockedSearch.mockResolvedValue(emptySearchResponse("python"));
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole("combobox"), "python");
    expect(mockedSearch).not.toHaveBeenCalled();

    await waitFor(() => expect(mockedSearch).toHaveBeenCalledTimes(1), { timeout: 1500 });
    expect(mockedSearch).toHaveBeenLastCalledWith("python", 10, expect.anything());
  });

  it("shows the degradation banner with per-shard status when the search comes back degraded", async () => {
    mockedSearch.mockResolvedValue({
      query: "python",
      results: [
        {
          doc_id: 1,
          url: "https://docs.python.org/3/tutorial/index.html",
          title: "The Python Tutorial",
          snippet: { text: "python is a popular language", highlights: [] },
          score: 4.5,
        },
      ],
      corrections: [],
      shard_statuses: [
        { shard_id: 0, status: "ok", error_message: null },
        { shard_id: 1, status: "timeout", error_message: "tiempo agotado" },
      ],
      degraded: true,
      message: "Resultados parciales: 1 de 2 nodos del índice no respondieron a tiempo.",
    });
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole("combobox"), "python");

    expect(await screen.findByRole("alert", {}, { timeout: 1500 })).toHaveTextContent(
      /Resultados parciales/,
    );
    expect(screen.getByText(/shard 1: sin respuesta/)).toBeInTheDocument();
    // Los resultados de los shards sanos siguen mostrándose, degradado no es "sin nada".
    expect(screen.getByText("The Python Tutorial")).toBeInTheDocument();
  });

  it("shows a no-results message when the search returns nothing and is not degraded", async () => {
    mockedSearch.mockResolvedValue(emptySearchResponse("qqxxzzyy"));
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole("combobox"), "qqxxzzyy");

    expect(
      await screen.findByText("No se encontraron resultados para esta búsqueda.", {}, {
        timeout: 1500,
      }),
    ).toBeInTheDocument();
  });

  it("surfaces a connection error without crashing when the API call rejects", async () => {
    const { ApiError } = await import("./api/client");
    mockedSearch.mockRejectedValue(
      new ApiError("No se pudo conectar con la API. ¿Está arrancada en el puerto 8000?", 0),
    );
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole("combobox"), "python");

    expect(
      await screen.findByText(/No se pudo conectar con la API/, {}, { timeout: 1500 }),
    ).toBeInTheDocument();
  });
});
