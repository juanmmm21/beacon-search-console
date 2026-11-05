import { ApiError } from "../api/client";
import type { DocsHealth, DocsSearchResponse, DocsSources, SearchMode } from "./types";

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/v1${path}`, { signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError("Could not reach the search API.", 0);
  }
  if (response.status === 429) {
    const retry = response.headers.get("Retry-After") ?? "a few";
    throw new ApiError(`Too many searches. Try again in ${retry} seconds.`, 429);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail) {
        detail = body.detail;
      }
    } catch {
      // sin cuerpo JSON: queda el statusText
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const docsApi = {
  search: (
    query: string,
    options: { limit: number; source: string | null; mode: SearchMode },
    signal?: AbortSignal,
  ) => {
    const params = new URLSearchParams({
      q: query,
      limit: String(options.limit),
      mode: options.mode,
    });
    if (options.source) {
      params.set("source", options.source);
    }
    return request<DocsSearchResponse>(`/search?${params.toString()}`, signal);
  },
  sources: (signal?: AbortSignal) => request<DocsSources>("/sources", signal),
  health: (signal?: AbortSignal) => request<DocsHealth>("/health", signal),
};
