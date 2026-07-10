# beacon-search-console

**Project 10/10 of the [`beacon-search-engine`](https://github.com/juanmmm21/beacon-search-engine) ecosystem** — the flagship application.
Repository: [`github.com/juanmmm21/beacon-search-console`](https://github.com/juanmmm21/beacon-search-console)

A complete, working search engine console — FastAPI backend + React/TypeScript
frontend — that assembles the nine infrastructure pieces of the ecosystem into
one product and runs them over a **real corpus**: 181 pages crawled live from
`docs.python.org/3` (tutorial + library reference), indexed, compressed,
partitioned into shards, and served with BM25 + PageRank + learning-to-rank
reranking, live autocomplete, spell correction, and highlighted snippets. No
Elasticsearch, no Lucene, no search SaaS anywhere in the stack: every layer
underneath this app is one of the ecosystem's own from-scratch projects.

## What problem it solves

Each of the nine previous projects proves one piece of search infrastructure
in isolation: a polite crawler, a boilerplate-stripping extractor, a
positional inverted index, a postings compression codec, a BM25 scorer, a
PageRank implementation, a gradient-boosted reranker, a query parser with
autocomplete, and a sharded fan-out/merge layer. None of them, alone, is a
search engine. This project is the proof that the ecosystem composes: it
wires all nine together — through the exact on-disk contracts and package
APIs each of them documents — into a product a person can actually use, over
content crawled from the real web, with the failure modes of a real system
(a shard process dying mid-session) handled visibly instead of crashing.

## Role in `beacon-search-engine`

```text
                     OFFLINE (scripts/bootstrap_corpus.sh)
┌──────────────────────────────────────────────────────────────────────────┐
│ web-crawler-scheduler ──▶ filter_corpus_domain.py ──▶ html-content-extractor │
│    │ link_graph.jsonl      (this project's own step,      │ documents.jsonl │
│    │                        keeps only the seed domain)   ▼ (main_text)     │
│    │                                              inverted-index-builder    │
│    │                                                     │ index/ (postings  │
│    │                                                     │  + stats)         │
│    │                                                     ▼                  │
│    │                                              index-compression-codec   │
│    │                                                     │ compressed index │
│    ▼                                                     ▼                  │
│ pagerank-link-analysis                       distributed-index-sharding     │
│    │ pagerank_scores                             `partition` -> shard-0..N/ │
│    └──────────────┐                                      │                  │
│                    │                          learning-to-rank-reranker     │
│                    │                                      │ trained model   │
└────────────────────┼──────────────────────────────────────┼──────────────────┘
                     ▼                                      ▼
                     ONLINE (this project)
┌──────────────────────────────────────────────────────────────────────────┐
│  FastAPI backend                                                          │
│    query ─▶ query-parser-autocomplete (parse + spellcheck)                │
│          ─▶ distributed-index-sharding (fan-out to N shard                │
│             processes, each scoring with bm25-ranking-engine,             │
│             k-way merge, tolerance to shard failure)                      │
│          ─▶ learning-to-rank-reranker (BM25 + PageRank + match            │
│             features, grouped per shard — see Architecture)               │
│          ─▶ snippets from html-content-extractor's documents.jsonl        │
│                                                                            │
│  React + TypeScript frontend                                              │
│    debounced search · live autocomplete · highlighted snippets ·          │
│    index stats panel · explicit shard-degradation banner                  │
└──────────────────────────────────────────────────────────────────────────┘
```

This is where the whole ecosystem converges — the app every other README
refers to as "converges in `beacon-search-console`".

## Goal and skills demonstrated

- **Orchestration, not reimplementation**: this app contains no tokenizer, no
  scorer, no ranking formula of its own. Parsing and autocomplete come from
  [`query-parser-autocomplete`](https://github.com/juanmmm21/query-parser-autocomplete),
  distributed scoring from
  [`distributed-index-sharding`](https://github.com/juanmmm21/distributed-index-sharding)
  (which delegates BM25 to
  [`bm25-ranking-engine`](https://github.com/juanmmm21/bm25-ranking-engine)
  inside each shard process), and the final ordering from
  [`learning-to-rank-reranker`](https://github.com/juanmmm21/learning-to-rank-reranker)
  combining BM25 with the authority scores of
  [`pagerank-link-analysis`](https://github.com/juanmmm21/pagerank-link-analysis).
  The backend's own code is glue: configuration, lifecycle, one integration
  bridge (below), and snippet presentation.
- **The one integration no other repo could own**: `distributed-index-sharding`
  merges per-shard BM25 results but knows nothing about reranking;
  `learning-to-rank-reranker` reranks against a single index directory but
  knows nothing about shards. Bridging them — grouping merged candidates by
  the shard that owns each `doc_id`, reranking per shard against that shard's
  local index, then re-merging with the ecosystem's standard deterministic
  tie-break — is exactly the kind of composition problem a flagship app
  exists to solve (`backend/src/beacon_search_console/reranking.py`).
- **Real corpus, reproducible bootstrap**: `scripts/bootstrap_corpus.sh` runs
  the six offline tools end to end against `docs.python.org` (allowed by its
  `robots.txt`, crawled with the polite rate-limiting
  [`web-crawler-scheduler`](https://github.com/juanmmm21/web-crawler-scheduler)
  enforces) — no canned fixtures in production, no fake data in the demo.
  `web-crawler-scheduler` has no domain-restriction flag of its own (it's a
  reusable crawling primitive, not scoped to any one corpus), so a crawl at
  `--max-depth 2` legitimately follows outbound links off `docs.python.org`
  (permalinks into `github.com/python/cpython`, mostly); `scripts/filter_corpus_domain.py`
  is this project's own intermediate step — never a change to the crawler
  itself — that keeps only the seed domain's pages before extraction, so the
  indexed corpus is exactly the "real corner of the web" this app set out to
  serve, not everything the crawl happened to reach.
- **Failure handled as a feature**: killing a shard process mid-session
  degrades the response (`degraded: true`, per-shard statuses, partial
  results from the healthy shards) instead of returning a 500 — surfaced in
  the UI as an explicit banner naming which shard is down and why.
- **Typed on both sides of the wire**: `mypy --strict` on the backend,
  TypeScript `strict` (plus `noUncheckedIndexedAccess`) on the frontend, and
  a hand-mirrored contract (`frontend/src/types/api.ts` ↔
  `backend/src/beacon_search_console/models.py`) for the versioned
  `/api/v1` API.

## How it works

A search request flows through the backend like this:

1. **Parse + spellcheck** — the raw string is parsed by
   `query-parser-autocomplete` (`parse_and_correct_query`): exact phrases,
   `-exclusions`, `site:` filters, and typo correction against the *global*
   index vocabulary (built once at startup from the unpartitioned index —
   shard-local vocabularies would miss corrections for terms living on other
   shards).
2. **Fan-out** — the resulting `ParsedQuery` JSON is handed to
   `DistributedSearchPipeline.search_parsed_query`, which asks every shard
   process concurrently over HTTP; each shard scores with its own
   `bm25-ranking-engine` instance and applies exclusions/`site:` filters
   locally. The coordinator k-way-merges the healthy shards' results and
   reports the failed ones — it never raises because a shard died.
3. **Rerank** — the merged candidates (over-fetched: `limit × 3` by default,
   so the reranker has real freedom to reorder) go through the
   sharding↔reranking bridge described above, producing the final order from
   BM25, PageRank, and index-derived match features.
4. **Snippets** — the ranked `doc_id`s are resolved back to real text. The
   indexing chain deliberately drops `main_text` (an index stores postings,
   not prose), so the backend loads `html-content-extractor`'s
   `documents.jsonl` at startup and correlates by `doc_id` = line number —
   the exact contract `inverted-index-builder` documents. A window around
   the first match is returned as plain text plus character-offset highlight
   ranges; the frontend wraps those ranges in `<mark>` itself (never
   `dangerouslySetInnerHTML` with server-built HTML).

Autocomplete (`/api/v1/autocomplete`) delegates to
`query-parser-autocomplete`'s two-trie suggester, built once at startup from
the global vocabulary (plus an optional query log). Index stats
(`/api/v1/index/stats`) read the builder's `stats.json`, the cluster
manifest, and the most recent `fetched_at` in the extractor's output.

## Architecture

```text
beacon-search-console/
├── scripts/
│   ├── bootstrap_corpus.sh       # offline pipeline: crawl → filter domain →
│   │                             # extract → index → compress → pagerank →
│   │                             # partition → train LTR
│   ├── filter_corpus_domain.py   # keeps only the seed domain's pages
│   │                             # (web-crawler-scheduler has no domain
│   │                             # restriction of its own, see Goal above)
│   └── tests/                   # unittest, stdlib only, no extra dependency
├── data/                      # bootstrap output (gitignored, reproducible)
├── samples/tiny_corpus/       # 5-doc deterministic fixture for backend tests
├── backend/
│   ├── pyproject.toml         # installs the 3 real package dependencies
│   └── src/beacon_search_console/
│       ├── config.py          # env-configurable paths/params (BEACON_*)
│       ├── models.py          # the API's own response contract
│       ├── dependencies.py    # AppState: everything opened once per process
│       ├── app.py             # FastAPI app + lifespan + /api/v1 routers
│       ├── reranking.py       # the sharding ↔ reranking bridge
│       ├── snippets.py        # doc_id → real text, highlight ranges
│       ├── index_stats.py     # minimal reader of the builder's stats.json
│       └── routes/            # search.py, autocomplete.py, stats.py
└── frontend/
    └── src/
        ├── api/client.ts      # typed fetch client for /api/v1
        ├── types/api.ts       # TS mirror of the backend contract
        ├── components/        # SearchBox (with autocomplete dropdown),
        │                      # SearchResults, SnippetText, StatsPanel,
        │                      # ShardStatusBanner — each with a Vitest +
        │                      # Testing Library test alongside it
        ├── hooks/useDebouncedValue.ts  # + its own debounce unit test
        └── App.tsx            # debounced search, ?q= URL sync
```

Two deliberate architecture decisions:

- **Offline/online separation.** The six tools that build artifacts (crawler,
  extractor, index builder, codec, PageRank, partitioner + LTR training) are
  installed into a disposable `.bootstrap-venv/` by the bootstrap script and
  never imported by the backend. The backend's own venv installs only the
  three packages the *online* path genuinely needs to call in-process:
  `distributed-index-sharding`, `query-parser-autocomplete`, and
  `learning-to-rank-reranker` (direct git-URL dependencies — the documented
  ecosystem exception for outputs that are in-memory only, first established
  by `bm25-ranking-engine`). Everything else is consumed through the on-disk
  formats each project documents.
- **Everything expensive opens once.** Shard subprocesses, the LightGBM
  model, the snippet table, the spellchecker, and the autocomplete tries are
  all built in the FastAPI lifespan and closed explicitly on shutdown —
  `DistributedSearchPipeline` owns the shard processes' lifecycle, so
  stopping the API stops the whole local cluster with it.

## Requirements

- Python `>=3.11`
- Node.js `>=20` (frontend)
- macOS: `brew install libomp` (LightGBM's OpenMP runtime, needed by
  `learning-to-rank-reranker`)
- The nine sibling repositories cloned next to this one (the bootstrap
  script installs the offline tools from the sibling folders; the backend
  installs its three package dependencies from GitHub)

## Bringing the whole engine up from scratch

```bash
git clone https://github.com/juanmmm21/beacon-search-console.git
cd beacon-search-console

# 1. Build the corpus and every artifact (crawls docs.python.org politely;
#    ~180 pages, a few minutes). Re-run anytime to refresh the corpus.
bash scripts/bootstrap_corpus.sh

# 2. Start the API (spawns one real shard process per shard and health-checks
#    them before serving).
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m beacon_search_console --port 8000

# 3. Start the UI (proxies /api to :8000).
cd ../frontend
npm install
npm run dev            # → http://localhost:5173
```

`MAX_PAGES`, `MAX_DEPTH` and `NUM_SHARDS` tune the bootstrap
(`MAX_PAGES=400 NUM_SHARDS=4 bash scripts/bootstrap_corpus.sh`). The backend
reads its paths and parameters from `BEACON_*` environment variables
(`config.py` documents each one); by default everything points at `data/`.

## API

The contract is versioned under `/api/v1` from the first commit. All
endpoints are `GET`.

| Endpoint | Parameters | Returns |
|---|---|---|
| `/api/v1/search` | `q` (query text), `limit` (1–50, default 10) | Ranked results with `url`, `title`, `score`, and a `snippet` (`text` + `highlights` as `{start, end}` character ranges); applied spelling `corrections`; per-shard `shard_statuses`; `degraded` flag and a human-readable `message` when the query was empty, matched nothing, or ran against a partially-down cluster |
| `/api/v1/autocomplete` | `q` (prefix), `limit` (1–20, default 8) | Ranked `suggestions` (`text`, `score`); an empty prefix returns the most frequent queries, `query-parser-autocomplete`'s documented "trending" default |
| `/api/v1/index/stats` | — | `total_documents`, `vocabulary_size`, `total_postings`, `average_document_length`, `num_shards`, `last_crawled_at` (most recent `fetched_at` in the corpus) |

A shard failing mid-query never produces a 500: the response arrives with
`degraded: true`, the failing shard's `status`/`error_message` in
`shard_statuses`, and results from the surviving shards.

## Frontend

- **Debounced search** (300 ms) with in-flight request cancellation — the
  latest keystroke always wins, one request per typing pause, never one per
  key.
- **Live autocomplete** (150 ms debounce) with full keyboard navigation
  (arrows / Enter / Escape), backed by `/api/v1/autocomplete`.
- **Snippet highlighting built from character ranges**: the API sends plain
  text plus offsets, and the UI constructs `<mark>` React nodes from them —
  no server-provided HTML is ever injected.
- **Explicit degradation UI**: if any shard is down, a banner names each
  shard's status and clarifies that results come from the healthy ones only.
- **Honest operator hints**: the search box itself states the v1 engine
  limitations (quoted phrases score as their individual terms — BM25 carries
  no positional adjacency through the sharded path — and only the `site:`
  filter has real semantics), inherited from `bm25-ranking-engine` /
  `distributed-index-sharding` and documented in their READMEs rather than
  discovered by surprise.
- Shareable searches: the query lives in the URL (`?q=`), updated with
  `replaceState` so typing doesn't pollute history.
- UI text is in Spanish, code identifiers in English — the ecosystem's
  standing convention.

## Development

```bash
# Backend (from backend/)
pytest                 # 24 tests, including real 2-shard cluster startup
ruff check src/ tests/
mypy --strict src/

# Frontend (from frontend/)
npm run test            # Vitest + Testing Library, 30 tests
npm run typecheck
npm run build

# scripts/filter_corpus_domain.py (from the repo root) — stdlib-only, no
# extra dependency, so plain unittest rather than pytest
python3 -m unittest discover -s scripts/tests
```

Backend tests run against `samples/tiny_corpus/` — a 5-document,
hand-written, fully deterministic fixture partitioned into 2 shards, with a
pre-trained tiny LTR model — so they exercise the *real*
`DistributedSearchPipeline` (actual shard subprocesses on test-only ports)
without network access or the bootstrapped corpus. Shard-failure degradation
is covered with an in-memory pipeline double, mirroring how
`distributed-index-sharding` tests its own coordinator; the
kill-a-real-process path is covered by that project's end-to-end suite and by
manual smoke testing here.

Frontend tests cover `SnippetText`'s range sanitation (out-of-bounds,
negative, overlapping and unsorted highlight ranges — never trusting the
backend's offsets blindly), the debounce hook in isolation
(`useDebouncedValue`, including the "several rapid changes collapse into one"
case the search box exists to guarantee), `SearchBox`'s live autocomplete
(debounce, keyboard navigation, a rejected request closing the dropdown
instead of throwing) against a mocked API client, `ShardStatusBanner`'s
degradation rendering, and `App`-level integration (one search request per
typing pause, the degraded banner rendering alongside the surviving shards'
results, a connection error surfacing instead of crashing).

## Troubleshooting

- **`FileNotFoundError: ... cluster_manifest.json` (or `stats.json`,
  `documents.jsonl`) at startup**: the corpus was never bootstrapped — run
  `bash scripts/bootstrap_corpus.sh` first, or point the `BEACON_*` variables
  at an existing data directory.
- **`OSError: ... libomp.dylib` on macOS**: LightGBM needs the OpenMP
  runtime — `brew install libomp`.
- **The API starts but every search comes back degraded with `error` on all
  shards**: another process is occupying the shard port range. The shards
  bind consecutive ports from `BEACON_SHARD_BASE_PORT` (default 9300) — free
  those ports or move the range.
- **Results whose snippet doesn't contain the query term**: expected for
  documents matched via a spelling-corrected or phrase-flattened term that
  appears in the document under a different token boundary; the snippet
  falls back to the start of the document rather than fabricating a match.
- **A quoted phrase returns the same results as its words separately / a
  `filetype:` filter does nothing**: v1 engine limitation inherited from the
  ranking stack (no positional adjacency in `bm25-ranking-engine`'s result;
  only `site:` has filter semantics) — documented in
  `distributed-index-sharding`'s Troubleshooting and stated in this UI.
- **A result points outside `docs.python.org`**: shouldn't happen —
  `filter_corpus_domain.py` runs right after the crawl and keeps only pages
  whose `url` host is exactly `docs.python.org`, so externally-linked pages
  the crawl reaches at `--max-depth 2` (mostly `github.com/python/cpython`
  permalinks) never make it into `extracted/documents.jsonl`. If one still
  shows up, `data/crawl/pages.jsonl` was likely edited or reused across a
  bootstrap run without going back through the filter step — re-run
  `bash scripts/bootstrap_corpus.sh` from a clean `data/` directory.
- **`mypy` fails under `backend/tests/`**: expected — only `src/` is
  type-checked in `--strict` mode, the same convention as every other
  project in the ecosystem.

## License

MIT — see [`LICENSE`](./LICENSE).
