import type { ReactNode } from "react";
import type { HighlightRange } from "../types/api";

interface SnippetTextProps {
  text: string;
  highlights: HighlightRange[];
}

/** Normaliza los rangos antes de pintar: ordenados, dentro de los límites del
 * texto y sin solapes (si dos se solapan, gana el primero) — así un rango
 * malformado degrada a "no se resalta", nunca a un render roto. */
function sanitizeRanges(text: string, highlights: HighlightRange[]): HighlightRange[] {
  const sorted = [...highlights].sort((a, b) => a.start - b.start);
  const clean: HighlightRange[] = [];
  let cursor = 0;
  for (const range of sorted) {
    const start = Math.max(range.start, cursor);
    const end = Math.min(range.end, text.length);
    if (start < end) {
      clean.push({ start, end });
      cursor = end;
    }
  }
  return clean;
}

/** Envuelve en `<mark>` los rangos de caracteres que declara el backend.
 * Nunca `dangerouslySetInnerHTML`: la API manda texto plano + offsets,
 * y aquí se construyen nodos React a partir de ellos. */
export function SnippetText({ text, highlights }: SnippetTextProps) {
  const ranges = sanitizeRanges(text, highlights);
  if (ranges.length === 0) {
    return <p className="snippet">{text}</p>;
  }

  const parts: ReactNode[] = [];
  let cursor = 0;
  ranges.forEach((range, index) => {
    if (range.start > cursor) {
      parts.push(text.slice(cursor, range.start));
    }
    parts.push(<mark key={index}>{text.slice(range.start, range.end)}</mark>);
    cursor = range.end;
  });
  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }

  return <p className="snippet">{parts}</p>;
}
