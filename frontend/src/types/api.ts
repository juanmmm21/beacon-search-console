// Espejo TypeScript, campo a campo, del contrato versionado /api/v1 que
// expone backend/src/beacon_search_console/models.py — el frontend nunca ve
// los tipos internos de los subproyectos orquestados, solo este contrato.

export interface HighlightRange {
  start: number;
  end: number;
}

export interface Snippet {
  text: string;
  highlights: HighlightRange[];
}

export interface SearchResultItem {
  doc_id: number;
  url: string;
  title: string;
  snippet: Snippet;
  score: number;
}

export type ShardStatus = "ok" | "timeout" | "error" | string;

export interface ShardStatusInfo {
  shard_id: number;
  status: ShardStatus;
  error_message: string | null;
}

export interface QueryCorrectionInfo {
  original: string;
  corrected: string;
}

export interface SearchResponse {
  query: string;
  results: SearchResultItem[];
  corrections: QueryCorrectionInfo[];
  shard_statuses: ShardStatusInfo[];
  degraded: boolean;
  message: string | null;
}

export interface AutocompleteSuggestion {
  text: string;
  score: number;
}

export interface AutocompleteResponse {
  prefix: string;
  suggestions: AutocompleteSuggestion[];
}

export interface IndexStatsResponse {
  total_documents: number;
  vocabulary_size: number;
  total_postings: number;
  average_document_length: number;
  num_shards: number;
  last_crawled_at: string | null;
}
