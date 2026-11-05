import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { SnippetText } from "../components/SnippetText";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { docsApi } from "./client";
import type { DocsHealth, DocsSearchResponse, DocsSources, SearchMode } from "./types";

const DEBOUNCE_MS = 250;
const RESULT_LIMIT = 10;

function initialParam(name: string): string | null {
  return new URLSearchParams(window.location.search).get(name);
}

function syncLocation(query: string, source: string | null, mode: SearchMode): void {
  const url = new URL(window.location.href);
  for (const [key, value] of [
    ["q", query],
    ["source", source ?? ""],
    ["mode", mode === "lexical" ? "" : mode],
  ] as const) {
    if (value) {
      url.searchParams.set(key, value);
    } else {
      url.searchParams.delete(key);
    }
  }
  window.history.replaceState(null, "", url);
}

export default function DocsApp() {
  const [query, setQuery] = useState(() => initialParam("q") ?? "");
  const [source, setSource] = useState<string | null>(() => initialParam("source"));
  const [mode, setMode] = useState<SearchMode>(() =>
    initialParam("mode") === "hybrid" ? "hybrid" : "lexical",
  );
  const [sources, setSources] = useState<DocsSources | null>(null);
  const [health, setHealth] = useState<DocsHealth | null>(null);
  const [response, setResponse] = useState<DocsSearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounced = useDebouncedValue(query, DEBOUNCE_MS);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([docsApi.sources(controller.signal), docsApi.health(controller.signal)])
      .then(([loadedSources, loadedHealth]) => {
        setSources(loadedSources);
        setHealth(loadedHealth);
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setError(caught instanceof ApiError ? caught.message : "Unexpected error.");
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const trimmed = debounced.trim();
    syncLocation(trimmed, source, mode);
    abortRef.current?.abort();
    if (!trimmed) {
      setResponse(null);
      setSearching(false);
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setSearching(true);
    docsApi
      .search(trimmed, { limit: RESULT_LIMIT, source, mode }, controller.signal)
      .then((body) => {
        setResponse(body);
        setError(null);
        setSearching(false);
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setError(caught instanceof ApiError ? caught.message : "Unexpected error.");
        setResponse(null);
        setSearching(false);
      });
    return () => controller.abort();
  }, [debounced, source, mode]);

  return (
    <div className="page">
      <header className="header">
        <h1 className="brand">
          <span className="brand-beacon">◉</span> beacon docs
        </h1>
        <p className="tagline">
          Search across Python, Rust and MDN Web Docs with a search engine built from scratch —
          crawler, inverted index, BM25 and hybrid retrieval, no Elasticsearch.
        </p>
      </header>

      <div className="searchbox">
        <label htmlFor="docs-query" className="visually-hidden">
          Search the documentation
        </label>
        <input
          id="docs-query"
          className="searchbox-input"
          type="search"
          value={query}
          placeholder="e.g. async context manager, borrow checker, flexbox gap"
          autoComplete="off"
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      <div className="docs-controls">
        <div className="chips" role="group" aria-label="Filter by source">
          <button
            type="button"
            className="chip"
            aria-pressed={source === null}
            onClick={() => setSource(null)}
          >
            All
          </button>
          {sources?.sources.map((item) => (
            <button
              key={item.source_id}
              type="button"
              className="chip"
              aria-pressed={source === item.source_id}
              onClick={() => setSource(item.source_id)}
            >
              {item.name}
            </button>
          ))}
        </div>
        {health?.hybrid && (
          <div className="chips" role="group" aria-label="Ranking">
            {(["lexical", "hybrid"] as const).map((value) => (
              <button
                key={value}
                type="button"
                className="chip"
                aria-pressed={mode === value}
                onClick={() => setMode(value)}
              >
                {value === "lexical" ? "BM25" : "Hybrid"}
              </button>
            ))}
          </div>
        )}
      </div>

      <main className="content">
        {error && (
          <div className="error-banner" role="alert">
            {error}
          </div>
        )}
        {searching && <p className="status-line">Searching…</p>}
        {!searching && response && response.results.length > 0 && (
          <>
            <p className="status-line">
              {response.results.length} results · {response.took_ms.toFixed(1)} ms
              {response.cached ? " · cached" : ""}
            </p>
            <ol className="results">
              {response.results.map((hit) => (
                <li key={hit.doc_id} className="result">
                  <div className="result-url">
                    {hit.source && <span className="source-badge">{hit.source.name}</span>}
                    {hit.url}
                  </div>
                  <h2 className="result-title">
                    <a href={hit.url} rel="noopener noreferrer">
                      {hit.title}
                    </a>
                  </h2>
                  <SnippetText text={hit.snippet.text} highlights={hit.snippet.highlights} />
                  {hit.source && (
                    <p className="result-license">
                      {hit.source.attribution} ·{" "}
                      <a href={hit.source.license_url} rel="noopener noreferrer">
                        {hit.source.license}
                      </a>
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </>
        )}
        {!searching && response && response.results.length === 0 && (
          <p className="status-line">No results for this search.</p>
        )}
        {!debounced.trim() && !error && health && (
          <p className="status-line status-idle">
            {health.documents.toLocaleString("en")} pages indexed. Results link to the original
            page; content belongs to each project under its license.
          </p>
        )}
      </main>

      {sources && (
        <footer className="docs-footer">
          <h2 className="stats-title">Sources and licenses</h2>
          <ul>
            {sources.sources.map((item) => (
              <li key={item.source_id}>
                <a href={item.home_url} rel="noopener noreferrer">
                  {item.name}
                </a>{" "}
                — {item.attribution},{" "}
                <a href={item.license_url} rel="noopener noreferrer">
                  {item.license}
                </a>
                {health?.documents_per_source[item.source_id] !== undefined &&
                  ` · ${health.documents_per_source[item.source_id]} pages`}
              </li>
            ))}
          </ul>
          <p className="docs-footer-note">
            Crawled politely: robots.txt and Crawl-delay are honored and every source has a page
            budget. Also available as a JSON API (<code>/v1/search</code>) and as an MCP server (
            <code>/mcp</code>) for agents.
          </p>
        </footer>
      )}
    </div>
  );
}
