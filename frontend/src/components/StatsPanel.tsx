import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { IndexStatsResponse } from "../types/api";

const NUMBER_FORMAT = new Intl.NumberFormat("es-ES");

function formatCrawledAt(iso: string | null): string {
  if (!iso) {
    return "—";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso; // ISO no parseable: mejor mostrarlo crudo que ocultarlo
  }
  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

/** Panel de estadísticas del índice (`/api/v1/index/stats`): se carga una vez
 * al montar — el índice no cambia mientras la API vive, así que no hay nada
 * que refrescar periódicamente. */
export function StatsPanel() {
  const [stats, setStats] = useState<IndexStatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .indexStats(controller.signal)
      .then((body) => {
        setStats(body);
        setError(null);
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === "AbortError") {
          return;
        }
        setError(
          requestError instanceof ApiError
            ? requestError.message
            : "No se pudieron cargar las estadísticas del índice.",
        );
      });
    return () => controller.abort();
  }, []);

  return (
    <section className="stats-panel" aria-label="Estadísticas del índice">
      <h2 className="stats-title">Estadísticas del índice</h2>
      {error && <p className="stats-error">{error}</p>}
      {!error && !stats && <p className="stats-error">Cargando…</p>}
      {stats && (
        <dl className="stats-grid">
          <div>
            <dt>documentos indexados</dt>
            <dd>{NUMBER_FORMAT.format(stats.total_documents)}</dd>
          </div>
          <div>
            <dt>términos únicos</dt>
            <dd>{NUMBER_FORMAT.format(stats.vocabulary_size)}</dd>
          </div>
          <div>
            <dt>postings totales</dt>
            <dd>{NUMBER_FORMAT.format(stats.total_postings)}</dd>
          </div>
          <div>
            <dt>longitud media (tokens)</dt>
            <dd>{NUMBER_FORMAT.format(Math.round(stats.average_document_length))}</dd>
          </div>
          <div>
            <dt>shards del índice</dt>
            <dd>{NUMBER_FORMAT.format(stats.num_shards)}</dd>
          </div>
          <div>
            <dt>último crawl</dt>
            <dd>{formatCrawledAt(stats.last_crawled_at)}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}
