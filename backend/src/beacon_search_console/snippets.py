"""Snippets de resultado a partir del texto real de `html-content-extractor`.

La cadena `inverted-index-builder` -> `index-compression-codec` ->
`bm25-ranking-engine` -> `distributed-index-sharding` solo transporta
`doc_id`, `url`, `title` y `length` por documento — el `main_text` que
`html-content-extractor` sí extrajo se descarta al construir el índice
invertido y no reaparece en ningún punto posterior (ver `../../PROGRESS.md`,
nota de handoff de `distributed-index-sharding`). Para mostrar snippets reales
hay que volver al `documents.jsonl` original de `html-content-extractor` y
correlacionar por `doc_id` — que `inverted-index-builder` documenta como "la
posición de línea 0-indexada exacta de ese `documents.jsonl` de entrada" — así
que la correlación solo es válida si es el mismo fichero que se usó para
construir el índice, sin reordenar ni deduplicar de nuevo entre medias
(`scripts/bootstrap_corpus.sh` garantiza esto: nunca se reescribe
`extracted/documents.jsonl` después de construir el índice sobre él).

El resaltado de coincidencias reimplementa, de forma mínima e independiente,
el mismo criterio de tokenización que usa todo el ecosistema (NFC + límites de
letra/dígito Unicode + `casefold()`) — no se importa el tokenizador de
`inverted-index-builder` (integración siempre vía formato en disco, nunca
imports cruzados, `../../AGENTS.md`), y aquí solo hace falta localizar
coincidencias en un fragmento de texto para pintarlas, no reconstruir el
índice."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from beacon_search_console.models import HighlightRange, Snippet

_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_SNIPPET_WINDOW_CHARS = 220
_SNIPPET_CONTEXT_BEFORE_CHARS = 60
_FALLBACK_SNIPPET_CHARS = 200


@dataclass(frozen=True, slots=True)
class DocumentText:
    """`url`/`title`/`main_text` de un documento, tal como los expone
    `html-content-extractor` — esta misma fuente resuelve tanto el snippet
    como los metadatos de display (`url`, `title`), porque `doc_id` es la
    posición de línea en este mismo fichero (el contrato que
    `inverted-index-builder` documenta y que el resto del pipeline
    hereda): no hace falta un segundo lector del índice global solo para
    metadatos, éste ya está alineado por construcción."""

    url: str
    title: str
    main_text: str


class SnippetIndex:
    """`doc_id -> DocumentText`, cargado una vez en memoria al arrancar la
    app: el corpus de este proyecto (cientos de páginas de documentación, no
    un índice web a escala real) cabe sin problema, así que no hace falta
    ningún acceso aleatorio a disco por petición."""

    def __init__(self, documents: tuple[DocumentText, ...]) -> None:
        self._documents = documents

    @classmethod
    def from_documents_path(cls, documents_path: Path) -> SnippetIndex:
        if not documents_path.exists():
            raise FileNotFoundError(
                f"no existe {documents_path}: ¿se ejecutó scripts/bootstrap_corpus.sh?"
            )
        documents: list[DocumentText] = []
        with documents_path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    # Preserva la alineación doc_id <-> línea aunque hubiera una
                    # línea vacía: perder una posición desalinearía todo doc_id
                    # posterior a ella.
                    documents.append(DocumentText(url="", title="", main_text=""))
                    continue
                data = json.loads(line)
                documents.append(
                    DocumentText(
                        url=str(data.get("url", "")),
                        title=str(data.get("title", "")),
                        main_text=str(data.get("main_text", "")),
                    )
                )
        return cls(tuple(documents))

    def __len__(self) -> int:
        return len(self._documents)

    def document(self, doc_id: int) -> DocumentText | None:
        if 0 <= doc_id < len(self._documents):
            return self._documents[doc_id]
        return None


def _normalized_tokens(text: str) -> list[tuple[str, int, int]]:
    """`(término_casefolded, start, end)` para cada run de letras/dígitos
    Unicode en `text` (ya normalizado a NFC por el llamador)."""
    return [
        (match.group().casefold(), match.start(), match.end())
        for match in _TOKEN_PATTERN.finditer(text)
    ]


def build_snippet(main_text: str, query_terms: Sequence[str]) -> Snippet:
    """Ventana de texto alrededor de la primera coincidencia de algún término
    de `query_terms`, con los rangos de coincidencia dentro de esa ventana ya
    resueltos. Sin ninguna coincidencia (candidato que solo matcheó por un
    término de una frase que no vive literalmente así en el texto, o texto
    vacío), cae al comienzo del documento sin resaltado — nunca un snippet
    vacío si hay texto disponible."""
    normalized_text = unicodedata.normalize("NFC", main_text)
    normalized_terms = {term.casefold() for term in query_terms if term}

    if not normalized_text:
        return Snippet(text="", highlights=())

    matches = [
        (start, end)
        for token, start, end in _normalized_tokens(normalized_text)
        if token in normalized_terms
    ]

    if not matches:
        window_text = normalized_text[:_FALLBACK_SNIPPET_CHARS].strip()
        suffix = "…" if len(normalized_text) > _FALLBACK_SNIPPET_CHARS else ""
        return Snippet(text=f"{window_text}{suffix}", highlights=())

    first_match_start = matches[0][0]
    window_start = max(0, first_match_start - _SNIPPET_CONTEXT_BEFORE_CHARS)
    window_end = min(len(normalized_text), window_start + _SNIPPET_WINDOW_CHARS)

    prefix = "…" if window_start > 0 else ""
    suffix = "…" if window_end < len(normalized_text) else ""
    offset = len(prefix) - window_start

    highlights = tuple(
        HighlightRange(start=start + offset, end=end + offset)
        for start, end in matches
        if window_start <= start and end <= window_end
    )
    return Snippet(
        text=f"{prefix}{normalized_text[window_start:window_end]}{suffix}",
        highlights=highlights,
    )


def latest_fetched_at(documents_path: Path) -> str | None:
    """`fetched_at` máximo entre todos los documentos de `documents_path`
    (comparación lexicográfica válida porque `web-crawler-scheduler` siempre
    escribe ISO 8601 con offset explícito) — la "última actualización del
    crawl" del panel de estadísticas. `None` solo si el fichero está vacío."""
    latest: str | None = None
    for entry in _iter_fetched_at(documents_path):
        if latest is None or entry > latest:
            latest = entry
    return latest


def _iter_fetched_at(documents_path: Path) -> Iterable[str]:
    if not documents_path.exists():
        return
    with documents_path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            data = json.loads(line)
            fetched_at = data.get("fetched_at")
            if isinstance(fetched_at, str) and fetched_at:
                yield fetched_at
