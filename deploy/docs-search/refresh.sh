#!/bin/sh
# Rastrea las fuentes curadas, aplica los cambios al índice segmentado y
# publica un bundle nuevo; la API lo recarga sola. Se repite cada
# BEACON_REFRESH_HOURS horas (por defecto, una vez por semana).
set -eu
while true; do
  echo "[refresh] $(date -u +%FT%TZ) rastreando fuentes"
  python -m beacon_scale_infra vertical-crawl \
    --sources /app/deploy/vertical-sources.json \
    --work-dir /data/crawl \
    --apply-inline \
    --storage-backend local --local-storage-root /data/storage \
    --bucket beacon-vertical --local-root /data/index-work
  python -m beacon_scale_infra export-vertical \
    --sources /app/deploy/vertical-sources.json \
    --output-root /bundles \
    --storage-backend local --local-storage-root /data/storage \
    --bucket beacon-vertical
  sleep "$(( ${BEACON_REFRESH_HOURS:-168} * 3600 ))"
done
