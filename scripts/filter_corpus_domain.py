"""Filtra `pages.jsonl` de `web-crawler-scheduler` para quedarnos solo con
las páginas del dominio semilla, antes de extraer/indexar.

`web-crawler-scheduler` no tiene ninguna opción nativa de restricción de
dominio (sigue outbound links hasta `max_depth` sin importar el host al que
apunten, por diseño: es una pieza de infraestructura reutilizable, no
específica de este corpus) — no toca ese repo por un caso de uso propio de
`beacon-search-console`, así que el filtro vive aquí, como paso intermedio
del bootstrap, entre el crawl y la extracción. Sin él, un crawl a
`--max-depth 2` sobre `docs.python.org` arrastra páginas externas (p. ej.
permalinks de `github.com/python/cpython` enlazados desde la propia
documentación) al corpus, que `html-content-extractor`/`inverted-index-builder`
tratarían como documentos indexables de pleno derecho aunque no formen parte
del "rincón concreto de la web" que se quiso indexar (`../../CLAUDE.md`, la
regla de oro de "un corpus real", no "todo lo que el crawler alcance").

No hace falta filtrar también `link_graph.jsonl`: `pagerank-link-analysis`
ya resuelve cada entrada (URL de origen y cada outlink) contra el
`url -> doc_id` de `documents.jsonl`, y descarta explícitamente — sin
lanzar, contándolo en `GraphBuildStats` — cualquier URL que no resuelva a un
documento indexado (ver su README, paso "Building the graph"). Una vez
`documents.jsonl` solo contiene páginas de `docs.python.org`, las entradas
del grafo que apuntan a páginas externas ya filtradas dejan de resolver por
sí solas, sin ningún cambio adicional aquí."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class FilterStats:
    total_lines: int
    kept: int
    dropped_wrong_domain: int
    dropped_malformed: int


def _hostname(url: str) -> str | None:
    """`None` si `url` no es una URL parseable o no declara host — nunca
    lanza, la misma tolerancia que el resto del ecosistema exige ante texto
    de entrada que puede estar mal formado (`../../CLAUDE.md`, sección 2.D)."""
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    return host.lower() if host else None


def filter_pages_by_domain(
    input_path: Path, output_path: Path, allowed_hosts: frozenset[str]
) -> FilterStats:
    """Copia a `output_path` solo las líneas de `input_path` (formato
    `pages.jsonl` de `web-crawler-scheduler`: una página por línea, con un
    campo `url`) cuyo host resuelve exactamente a uno de `allowed_hosts`.
    `output_path` puede ser el mismo fichero que `input_path` (sobrescritura
    in situ): se escribe primero a un fichero temporal en el mismo
    directorio y se reemplaza atómicamente (`os.replace`) solo al terminar
    de leer todo el origen, así que un fallo a mitad de proceso nunca deja
    `output_path` truncado ni corrompe la lectura en curso.

    Una línea que no es JSON válido o no tiene `url` se cuenta como
    descartada por malformada, nunca aborta el filtrado completo — mismo
    principio de "una entrada rota no tumba el lote" que aplica
    `html-content-extractor` a páginas individuales."""
    total = kept = dropped_wrong_domain = dropped_malformed = 0
    fd, tmp_name = tempfile.mkstemp(
        dir=str(output_path.parent), prefix=f".{output_path.name}.", suffix=".tmp"
    )
    try:
        with (
            os.fdopen(fd, "w", encoding="utf-8") as tmp_handle,
            input_path.open(encoding="utf-8") as source,
        ):
            for raw_line in source:
                line = raw_line.strip()
                if not line:
                    continue
                total += 1
                try:
                    record = json.loads(line)
                    host = _hostname(str(record["url"]))
                except (json.JSONDecodeError, KeyError, TypeError):
                    dropped_malformed += 1
                    continue
                if host in allowed_hosts:
                    tmp_handle.write(line + "\n")
                    kept += 1
                else:
                    dropped_wrong_domain += 1
        os.replace(tmp_name, output_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return FilterStats(
        total_lines=total,
        kept=kept,
        dropped_wrong_domain=dropped_wrong_domain,
        dropped_malformed=dropped_malformed,
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Filtra un pages.jsonl de web-crawler-scheduler para quedarse solo "
            "con un conjunto de dominios permitidos, antes de extraer/indexar."
        )
    )
    parser.add_argument("input_path", type=Path)
    parser.add_argument("output_path", type=Path)
    parser.add_argument(
        "--allowed-domain",
        action="append",
        dest="allowed_domains",
        required=True,
        help="Host permitido (repetible); comparación exacta insensible a mayúsculas.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    allowed_hosts = frozenset(domain.lower() for domain in args.allowed_domains)
    stats = filter_pages_by_domain(args.input_path, args.output_path, allowed_hosts)
    print(
        f"filtrado de dominio: {stats.kept}/{stats.total_lines} páginas conservadas "
        f"({stats.dropped_wrong_domain} fuera de dominio, "
        f"{stats.dropped_malformed} líneas malformadas descartadas)"
    )


if __name__ == "__main__":
    main()
