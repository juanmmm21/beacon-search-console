import type { AutocompleteResponse, IndexStatsResponse, SearchResponse } from "../types/api";

const API_BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error; // cancelación deliberada (tecleo rápido), no un fallo de red
    }
    throw new ApiError(
      "No se pudo conectar con la API. ¿Está arrancada en el puerto 8000?",
      0,
    );
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail) {
        detail = body.detail;
      }
    } catch {
      // sin cuerpo JSON: nos quedamos con el statusText
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  search: (query: string, limit: number, signal?: AbortSignal) =>
    request<SearchResponse>(
      `/search?q=${encodeURIComponent(query)}&limit=${limit}`,
      signal,
    ),
  autocomplete: (prefix: string, limit: number, signal?: AbortSignal) =>
    request<AutocompleteResponse>(
      `/autocomplete?q=${encodeURIComponent(prefix)}&limit=${limit}`,
      signal,
    ),
  indexStats: (signal?: AbortSignal) => request<IndexStatsResponse>("/index/stats", signal),
};
