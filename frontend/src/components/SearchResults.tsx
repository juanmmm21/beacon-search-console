import type { SearchResultItem } from "../types/api";
import { SnippetText } from "./SnippetText";

interface SearchResultsProps {
  results: SearchResultItem[];
}

export function SearchResults({ results }: SearchResultsProps) {
  return (
    <section aria-label="Resultados de búsqueda">
      {/* Encabezado real, no decorativo: sin él, los <h3> de cada resultado
          saltarían del <h1> de la cabecera directamente a nivel 3, un salto
          de nivel que las herramientas de accesibilidad (axe, lectores de
          pantalla) marcan como error — visualmente oculto porque la propia
          caja de búsqueda ya deja claro que esto son resultados. */}
      <h2 className="visually-hidden">Resultados de búsqueda</h2>
      <ol className="results">
        {results.map((result) => (
          <li key={result.doc_id} className="result">
            <span className="result-url">{result.url}</span>
            <h3 className="result-title">
              <a href={result.url} target="_blank" rel="noopener noreferrer">
                {result.title || result.url}
              </a>
            </h3>
            <SnippetText text={result.snippet.text} highlights={result.snippet.highlights} />
            <span className="result-score" title="Score final del reranker (learning-to-rank)">
              score {result.score.toFixed(4)}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
