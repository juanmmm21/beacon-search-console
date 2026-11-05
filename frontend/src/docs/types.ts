// Espejo TypeScript del contrato público /v1 del buscador de documentación
// (backend/src/beacon_search_console/public_api.py).
import type { Snippet } from "../types/api";

export interface SourceInfo {
  source_id: string;
  name: string;
  license: string;
  license_url: string;
  attribution: string;
  home_url: string;
}

export interface DocsSearchHit {
  doc_id: number;
  url: string;
  title: string;
  snippet: Snippet;
  score: number;
  source: SourceInfo | null;
}

export type SearchMode = "lexical" | "hybrid";

export interface DocsSearchResponse {
  query: string;
  mode: SearchMode;
  index_version: string;
  cached: boolean;
  took_ms: number;
  results: DocsSearchHit[];
}

export interface DocsSources {
  sources: SourceInfo[];
  disabled: { source_id: string; reason: string }[];
}

export interface DocsHealth {
  status: string;
  index_version: string;
  created_at: string;
  documents: number;
  documents_per_source: Record<string, number>;
  hybrid: boolean;
}
