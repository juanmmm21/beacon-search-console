#!/usr/bin/env bash
# Ejecuta de principio a fin el pipeline offline del ecosistema
# (crawler -> extractor -> builder -> codec -> pagerank -> sharding -> modelo LTR)
# sobre un corpus real: la sección "3. Object" / tutorial y referencia de
# biblioteca de docs.python.org (permitido por su robots.txt).
#
# Este script instala las herramientas de las 6 piezas anteriores del
# ecosistema en un venv propio y desechable (`.bootstrap-venv/`, nunca el
# venv de `backend/`, que solo necesita las 3 dependencias de paquete real
# documentadas en `backend/pyproject.toml`) — es la separación explícita
# entre "pipeline offline de indexación" y "runtime de consulta online" que
# documenta el README, sección Arquitectura.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ECOSYSTEM_ROOT="$(cd "${ROOT_DIR}/.." && pwd)"
DATA_DIR="${ROOT_DIR}/data"
VENV_DIR="${ROOT_DIR}/.bootstrap-venv"

SEED_URLS=(
  "https://docs.python.org/3/tutorial/index.html"
  "https://docs.python.org/3/library/index.html"
)
MAX_PAGES="${MAX_PAGES:-180}"
MAX_DEPTH="${MAX_DEPTH:-2}"
NUM_SHARDS="${NUM_SHARDS:-3}"
# `--max-depth 2` sigue outbound links dos saltos desde las semillas, y
# docs.python.org enlaza a páginas de github.com (permalinks "Edit on
# GitHub", historial de cpython...) que web-crawler-scheduler no tiene forma
# de excluir por sí solo (no ofrece restricción de dominio, ver
# scripts/filter_corpus_domain.py). ALLOWED_DOMAINS acota el corpus resultante
# a lo que realmente se quiso indexar.
ALLOWED_DOMAINS=("docs.python.org")

echo "== beacon-search-console: bootstrap del corpus real (docs.python.org/3) =="

if [ ! -d "${VENV_DIR}" ]; then
  python3 -m venv "${VENV_DIR}"
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
pip install -q --upgrade pip

echo "-- instalando las 6 herramientas offline del ecosistema (editable, local) --"
pip install -q -e "${ECOSYSTEM_ROOT}/web-crawler-scheduler"
pip install -q -e "${ECOSYSTEM_ROOT}/html-content-extractor"
pip install -q -e "${ECOSYSTEM_ROOT}/inverted-index-builder"
pip install -q -e "${ECOSYSTEM_ROOT}/index-compression-codec"
pip install -q -e "${ECOSYSTEM_ROOT}/pagerank-link-analysis"
pip install -q -e "${ECOSYSTEM_ROOT}/distributed-index-sharding"

mkdir -p "${DATA_DIR}"/{crawl,extracted,index,index-compressed,pagerank,shards,ltr-model}

echo "-- 1/6 crawler: web-crawler-scheduler --"
web-crawler-scheduler crawl \
  $(for u in "${SEED_URLS[@]}"; do printf -- "--seed %s " "$u"; done) \
  --output-dir "${DATA_DIR}/crawl" \
  --max-pages "${MAX_PAGES}" \
  --max-depth "${MAX_DEPTH}" \
  --max-concurrent-requests 8 \
  --max-concurrent-per-domain 4 \
  --min-delay-seconds 0.25

echo "-- filtro de dominio: descarta páginas fuera de ${ALLOWED_DOMAINS[*]} seguidas por outlinks --"
python3 "${ROOT_DIR}/scripts/filter_corpus_domain.py" \
  "${DATA_DIR}/crawl/pages.jsonl" "${DATA_DIR}/crawl/pages.jsonl" \
  $(for d in "${ALLOWED_DOMAINS[@]}"; do printf -- "--allowed-domain %s " "$d"; done)

echo "-- 2/6 extractor: html-content-extractor --"
html-content-extractor extract "${DATA_DIR}/crawl/pages.jsonl" \
  --output-dir "${DATA_DIR}/extracted"

echo "-- 3/6 índice invertido: inverted-index-builder --"
inverted-index-builder build "${DATA_DIR}/extracted/documents.jsonl" \
  --output-dir "${DATA_DIR}/index"

echo "-- 4/6 compresión: index-compression-codec --"
index-compression-codec compress "${DATA_DIR}/index" \
  --output-dir "${DATA_DIR}/index-compressed"

echo "-- 5/6 pagerank: pagerank-link-analysis --"
pagerank-link-analysis compute \
  "${DATA_DIR}/index/documents.jsonl" \
  "${DATA_DIR}/crawl/link_graph.jsonl" \
  "${DATA_DIR}/pagerank"

echo "-- 6/6 sharding: distributed-index-sharding (particiona el índice comprimido) --"
rm -rf "${DATA_DIR}/shards"
distributed-index-sharding partition "${DATA_DIR}/index-compressed" "${DATA_DIR}/shards" \
  --num-shards "${NUM_SHARDS}"

echo "-- entrenando el modelo de reranking: learning-to-rank-reranker --"
pip install -q -e "${ECOSYSTEM_ROOT}/learning-to-rank-reranker"
learning-to-rank-reranker train "${DATA_DIR}/ltr-model" \
  --num-queries 300 --candidates-per-query 25 --seed 42

echo "== bootstrap completo =="
inverted-index-builder stats "${DATA_DIR}/index"
echo "Shards: ${NUM_SHARDS} en ${DATA_DIR}/shards"
echo "Modelo LTR: ${DATA_DIR}/ltr-model"
