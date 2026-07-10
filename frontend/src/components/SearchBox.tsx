import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import type { AutocompleteSuggestion } from "../types/api";

interface SearchBoxProps {
  value: string;
  onChange: (value: string) => void;
}

const AUTOCOMPLETE_DEBOUNCE_MS = 150;
const AUTOCOMPLETE_LIMIT = 8;

export function SearchBox({ value, onChange }: SearchBoxProps) {
  const [suggestions, setSuggestions] = useState<AutocompleteSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  // El dropdown solo reacciona a lo que el usuario teclea, nunca a un valor
  // fijado programáticamente al elegir una sugerencia — si no, elegir una
  // reabriría el dropdown con las sugerencias de la query recién elegida.
  const [typedValue, setTypedValue] = useState<string | null>(null);
  const debouncedTyped = useDebouncedValue(typedValue, AUTOCOMPLETE_DEBOUNCE_MS);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    abortRef.current?.abort();
    if (debouncedTyped === null || !debouncedTyped.trim()) {
      setSuggestions([]);
      setOpen(false);
      setActiveIndex(-1);
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    api
      .autocomplete(debouncedTyped, AUTOCOMPLETE_LIMIT, controller.signal)
      .then((body) => {
        setSuggestions(body.suggestions);
        setOpen(body.suggestions.length > 0);
        setActiveIndex(-1);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        // El autocompletado es una ayuda, no una función crítica: si la API
        // falla aquí, se cierra el dropdown y la búsqueda sigue funcionando
        // (el error de conexión real ya lo comunica la vista de resultados).
        setSuggestions([]);
        setOpen(false);
      });

    return () => controller.abort();
  }, [debouncedTyped]);

  const applySuggestion = (text: string) => {
    onChange(text);
    setTypedValue(null);
    setSuggestions([]);
    setOpen(false);
    setActiveIndex(-1);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || suggestions.length === 0) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => (index + 1) % suggestions.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => (index <= 0 ? suggestions.length - 1 : index - 1));
    } else if (event.key === "Enter" && activeIndex >= 0) {
      const active = suggestions[activeIndex];
      if (active) {
        event.preventDefault();
        applySuggestion(active.text);
      }
    } else if (event.key === "Escape") {
      setOpen(false);
      setActiveIndex(-1);
    }
  };

  return (
    <div className="searchbox">
      <input
        type="search"
        className="searchbox-input"
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
          setTypedValue(event.target.value);
        }}
        onKeyDown={handleKeyDown}
        onBlur={() => {
          // Retraso mínimo para que un click en una sugerencia (que hace blur
          // antes que el onClick) llegue a aplicarse.
          window.setTimeout(() => setOpen(false), 120);
        }}
        onFocus={() => {
          if (suggestions.length > 0 && typedValue !== null) {
            setOpen(true);
          }
        }}
        placeholder="Busca en la documentación indexada… (admite -exclusión y site:dominio)"
        aria-label="Buscar"
        aria-expanded={open}
        aria-autocomplete="list"
        role="combobox"
        aria-controls="autocomplete-suggestions"
        autoFocus
        spellCheck={false}
        autoComplete="off"
      />
      {open && (
        <ul className="suggestions" id="autocomplete-suggestions" role="listbox">
          {suggestions.map((suggestion, index) => (
            <li
              key={suggestion.text}
              className={`suggestion${index === activeIndex ? " active" : ""}`}
              role="option"
              aria-selected={index === activeIndex}
              onMouseDown={(event) => {
                // mousedown, no click: se dispara antes del blur del input.
                event.preventDefault();
                applySuggestion(suggestion.text);
              }}
              onMouseEnter={() => setActiveIndex(index)}
            >
              <span>{suggestion.text}</span>
              <span className="suggestion-score">{suggestion.score}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="searchbox-hint">
        Limitación v1 del motor: las frases entre comillas se puntúan como sus términos sueltos
        (sin adyacencia real) y, de los filtros <code>campo:valor</code>, solo{" "}
        <code>site:</code> tiene efecto.
      </p>
    </div>
  );
}
