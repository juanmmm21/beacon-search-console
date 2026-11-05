import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { docsApi } from "./client";
import DocsApp from "./DocsApp";
import type { DocsHealth, DocsSearchResponse, DocsSources } from "./types";

vi.mock("./client", () => ({
  docsApi: { search: vi.fn(), sources: vi.fn(), health: vi.fn() },
}));

const mockedSearch = vi.mocked(docsApi.search);
const mockedSources = vi.mocked(docsApi.sources);
const mockedHealth = vi.mocked(docsApi.health);

const python = {
  source_id: "python",
  name: "Python 3 documentation",
  license: "PSF License Version 2",
  license_url: "https://docs.python.org/3/license.html",
  attribution: "© Python Software Foundation",
  home_url: "https://docs.python.org/3/",
};
const rust = {
  source_id: "rust",
  name: "The Rust Programming Language",
  license: "MIT OR Apache-2.0",
  license_url: "https://github.com/rust-lang/book/blob/main/LICENSE-MIT",
  attribution: "© The Rust Project Developers",
  home_url: "https://doc.rust-lang.org/book/",
};

const sources: DocsSources = { sources: [python, rust], disabled: [] };
const health: DocsHealth = {
  status: "ok",
  index_version: "abc",
  created_at: "2026-11-05T09:00:00+00:00",
  documents: 1194,
  documents_per_source: { python: 400, rust: 396 },
  hybrid: true,
};

function response(query: string): DocsSearchResponse {
  return {
    query,
    mode: "lexical",
    index_version: "abc",
    cached: false,
    took_ms: 3.2,
    results: [
      {
        doc_id: 7,
        url: "https://docs.python.org/3/library/asyncio-task.html",
        title: "Coroutines and tasks",
        snippet: { text: "asyncio.timeout() is an async context manager", highlights: [{ start: 0, end: 7 }] },
        score: 9.1,
        source: python,
      },
    ],
  };
}

describe("DocsApp", () => {
  beforeEach(() => {
    mockedSources.mockResolvedValue(sources);
    mockedHealth.mockResolvedValue(health);
    mockedSearch.mockImplementation((query) => Promise.resolve(response(query)));
    window.history.replaceState(null, "", "/docs.html");
  });

  it("searches and shows the source, link and license of each result", async () => {
    render(<DocsApp />);
    await userEvent.type(screen.getByRole("searchbox"), "async timeout");

    const link = await screen.findByRole("link", { name: "Coroutines and tasks" });
    expect(link).toHaveAttribute("href", "https://docs.python.org/3/library/asyncio-task.html");
    expect(screen.getAllByText("© Python Software Foundation", { exact: false }).length).toBeGreaterThan(0);
    expect(mockedSearch).toHaveBeenLastCalledWith(
      "async timeout",
      { limit: 10, source: null, mode: "lexical" },
      expect.any(AbortSignal),
    );
    expect(window.location.search).toContain("q=async+timeout");
  });

  it("filters by source and switches to hybrid ranking", async () => {
    render(<DocsApp />);
    await userEvent.type(screen.getByRole("searchbox"), "iterators");
    await screen.findByRole("link", { name: "Coroutines and tasks" });

    await userEvent.click(screen.getByRole("button", { name: "The Rust Programming Language" }));
    await waitFor(() =>
      expect(mockedSearch).toHaveBeenLastCalledWith(
        "iterators",
        { limit: 10, source: "rust", mode: "lexical" },
        expect.any(AbortSignal),
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Hybrid" }));
    await waitFor(() =>
      expect(mockedSearch).toHaveBeenLastCalledWith(
        "iterators",
        { limit: 10, source: "rust", mode: "hybrid" },
        expect.any(AbortSignal),
      ),
    );
    expect(screen.getByRole("button", { name: "Hybrid" })).toHaveAttribute("aria-pressed", "true");
  });

  it("lists sources with their licenses and has no accessibility violations", async () => {
    const { container } = render(<DocsApp />);
    expect(await screen.findByText("Sources and licenses")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "MIT OR Apache-2.0" })).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });
});
