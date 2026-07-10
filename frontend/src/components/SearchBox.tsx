interface SearchBoxProps {
  value: string;
  onChange: (value: string) => void;
}

export function SearchBox({ value, onChange }: SearchBoxProps) {
  return (
    <div className="searchbox">
      <input
        type="search"
        className="searchbox-input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Busca en la documentación indexada… (admite -exclusión y site:dominio)"
        aria-label="Buscar"
        autoFocus
        spellCheck={false}
        autoComplete="off"
      />
      <p className="searchbox-hint">
        Limitación v1 del motor: las frases entre comillas se puntúan como sus términos sueltos
        (sin adyacencia real) y, de los filtros <code>campo:valor</code>, solo{" "}
        <code>site:</code> tiene efecto.
      </p>
    </div>
  );
}
