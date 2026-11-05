# Deploying Beacon Docs

Beacon Docs is the public documentation search of `beacon-search-console`.
This guide brings it up on one machine with Docker Compose and estimates what
it costs to keep it running. Nothing here has been deployed yet.

## What runs

`deploy/docs-search/docker-compose.yml` starts three services:

- **refresher** (image of `beacon-search-engine-at-scale`): crawls the curated
  sources within their prefixes and page budgets, honoring robots.txt and
  Crawl-delay, applies the result to the segmented index and exports a new
  bundle to the `bundles` volume. It repeats every `BEACON_REFRESH_HOURS`
  (one week by default).
- **api** (`Dockerfile.api`): `beacon-search-console docs`, the `/v1` API and
  the `/mcp` endpoint. It loads the bundle at startup and hot-reloads every
  new one; with `BEACON_DOCS_HYBRID=1` it also loads the embedding model and
  the cross-encoder (downloaded once into the `hf-cache` volume).
- **web** (`Dockerfile.web`): Caddy serving the static frontend and proxying
  `/v1` and `/mcp` to the API, with automatic HTTPS for `BEACON_DOMAIN`.

At this scale (thousands of pages) the pipeline needs neither MinIO nor
Redis: it uses local disk and applies updates in the same process. The
at-scale repository runs the same flow over MinIO and Redis (its `vertical`
Compose profile) when one machine stops being enough.

## Steps

```bash
git clone https://github.com/juanmmm21/beacon-search-console.git
cd beacon-search-console/deploy/docs-search
cp .env.example .env
# Edit .env: BEACON_DOMAIN=docs.example.com and
# BEACON_MCP_ALLOWED_HOSTS=docs.example.com,docs.example.com:*
docker compose up -d --build
docker compose logs -f refresher   # first crawl: about 7 minutes for 1,200 pages
curl -s https://docs.example.com/v1/health
```

Point the domain's A/AAAA records to the server before starting `web`, so
Caddy can obtain the certificate. Until the first crawl finishes, the API
waits for a bundle and restarts (`restart: unless-stopped`).

## Sizing

Measured on the development machine (see the README, "Result cache and
latency"):

- BM25 only: the API process uses a few hundred MB; one vCPU is plenty.
- Hybrid: PyTorch plus two MiniLM models add roughly 1 GB of RAM, and an
  uncached hybrid search takes about 0.4 s of CPU on a Ryzen 7 7700X; expect
  more on a small VM. The cache absorbs repeated queries.
- The crawl stores raw pages and checkpoints (about 235 MB for 1,200 pages,
  mostly MDN) and the two most recent bundles take about 84 MB.

So **2 vCPU, 4 GB RAM and 40 GB of disk** is a comfortable floor with hybrid
search on; 1 vCPU and 2 GB is enough with `BEACON_DOCS_HYBRID=0`.

## Estimated cost

Prices as published in November 2026; check them before ordering, they
changed during 2026.

- **Hetzner Cloud CX23** (2 vCPU, 4 GB, 40 GB, 20 TB traffic): about
  €5.49/month, about €5.99 with a public IPv4. The CX33 (4 vCPU, 8 GB) is
  about €8.49/month and would leave room for a larger corpus. Hetzner raised
  CX prices on 15 June 2026, and one review reports the CX23 as temporarily
  unorderable in October 2026.
- **Oracle Cloud Always Free**: Ampere A1 capacity was cut on 15 June 2026 to
  the equivalent of 2 OCPUs and 12 GB per tenancy. That still fits this
  deployment at €0, with Oracle's known caveats (capacity is often
  unavailable in popular regions, and idle instances may be reclaimed).
- **Domain**: from about €10/year, unless a subdomain of an existing domain
  is used.
- **Egress**: negligible at this scale (JSON responses of a few KB; 20 TB is
  included on Hetzner).

Expected total: **about €6/month on Hetzner, or €0–1/month on Oracle's free
tier**, plus the domain if a new one is needed. No paid APIs are involved:
the models run locally.

## Before going public

- Read each source's license again (`deploy/vertical-sources.json` in
  at-scale): the product shows snippets and full text with attribution and a
  link to the original page; MDN's CC-BY-SA 2.5 also asks that derived
  material keep the same license.
- Set a contact URL in the crawler's user agent if the bot will run often.
- Keep the rate limits (`BEACON_RATE_*`) on: the API is unauthenticated.
