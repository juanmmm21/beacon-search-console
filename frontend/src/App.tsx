import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api/client";
import { SearchBox } from "./components/SearchBox";
import { SearchResults } from "./components/SearchResults";
import { ShardStatusBanner } from "./components/ShardStatusBanner";
import { StatsPanel } from "./components/StatsPanel";
import { useDebouncedValue } from "./hooks/useDebouncedValue";
import type { SearchResponse } from "./types/api";

const SEARCH_DEBOUNCE_MS = 300;
const RESULT_LIMIT = 10;

/** La query vive también en la URL (`?q=`), como en cualquier buscador:
 * una búsqueda es un enlace compartible y sobrevive a recargar la página. */
function queryFromLocation(): string {
  return new URLSearchParams(window.location.search).get("q") ?? "";
}

function syncQueryToLocation(query: string): void {
  const url = new URL(window.location.href);
  if (query) {
    url.searchParams.set("q", query);
  } else {
    url.searchParams.delete("q");
  }
  // replaceState, no pushState: cada tecla no debe crear una entrada de
  // historial nueva.
  window.history.replaceState(null, "", url);
}

export default function App() {
  const [query, setQuery] = useState(queryFromLocation);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const debouncedQuery = useDebouncedValue(query, SEARCH_DEBOUNCE_MS);
  // Aborta la petición en vuelo cuando el usuario sigue tecleando: la última
  // query gana siempre, sin carreras entre respuestas fuera de orden.
  const searchAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const trimmed = debouncedQuery.trim();
    syncQueryToLocation(trimmed);
    searchAbortRef.current?.abort();

    if (!trimmed) {
      setResponse(null);
      setSearching(false);
      setApiError(null);
      return;
    }

    const controller = new AbortController();
    searchAbortRef.current = controller;
    setSearching(true);

    api
      .search(trimmed, RESULT_LIMIT, controller.signal)
      .then((body) => {
        setResponse(body);
        setApiError(null);
        setSearching(false);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return; // superada por una query más reciente
        }
        setApiError(
          error instanceof ApiError ? error.message : "Error inesperado consultando la API.",
        );
        setResponse(null);
        setSearching(false);
      });

    return () => controller.abort();
  }, [debouncedQuery]);

  const hasQuery = debouncedQuery.trim().length > 0;

  return (
    <div className="page">
      <header className="header">
        <h1 className="brand">
          <span className="brand-beacon">◉</span> beacon
        </h1>
        <p className="tagline">
          Buscador propio de principio a fin: crawling, índice invertido, BM25, PageRank y
          reranking learning-to-rank — sin Elasticsearch ni Lucene.
        </p>
      </header>

      <SearchBox value={query} onChange={setQuery} />

      <main className="content">
        {apiError && (
          <div className="error-banner" role="alert">
            {apiError}
          </div>
        )}

        {response?.degraded && (
          <ShardStatusBanner message={response.message} shardStatuses={response.shard_statuses} />
        )}

        {response && response.corrections.length > 0 && (
          <p className="corrections">
            Buscando con correcciones:{" "}
            {response.corrections.map((correction, index) => (
              <span key={correction.original}>
                {index > 0 && ", "}
                <s>{correction.original}</s> → <strong>{correction.corrected}</strong>
              </span>
            ))}
          </p>
        )}

        {searching && <p className="status-line">Buscando…</p>}

        {!searching && response && response.results.length > 0 && (
          <SearchResults results={response.results} />
        )}

        {!searching && response && response.results.length === 0 && !response.degraded && (
          <p className="status-line">
            {response.message ?? "No se encontraron resultados para esta búsqueda."}
          </p>
        )}

        {!hasQuery && !apiError && (
          <p className="status-line status-idle">
            Escribe arriba para buscar en el corpus indexado.
          </p>
        )}

        <StatsPanel />
      </main>
    </div>
  );
}
