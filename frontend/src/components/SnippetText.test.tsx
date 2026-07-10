import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SnippetText } from "./SnippetText";

describe("SnippetText", () => {
  it("renders plain text with no <mark> when there are no highlights", () => {
    render(<SnippetText text="sin coincidencias aquí" highlights={[]} />);

    expect(screen.getByText("sin coincidencias aquí")).toBeInTheDocument();
    expect(screen.queryByText("sin coincidencias aquí")?.querySelector("mark")).toBeNull();
  });

  it("wraps a single highlight range in <mark>", () => {
    render(<SnippetText text="el python tutorial" highlights={[{ start: 3, end: 9 }]} />);

    const mark = screen.getByText("python");
    expect(mark.tagName).toBe("MARK");
  });

  it("renders multiple non-overlapping highlights independently", () => {
    render(
      <SnippetText
        text="python y tutorial de python"
        highlights={[
          { start: 0, end: 6 },
          { start: 21, end: 27 },
        ]}
      />,
    );

    const marks = screen.getAllByText("python");
    expect(marks).toHaveLength(2);
    marks.forEach((mark) => expect(mark.tagName).toBe("MARK"));
  });

  // El backend nunca debería mandar un rango fuera de límites o negativo,
  // pero si lo hiciera (un bug de otro subproyecto, una respuesta corrupta),
  // el componente debe degradar a "recortar el rango dentro del texto",
  // nunca lanzar ni renderizar basura.
  it("clamps a highlight whose end goes past the end of the text", () => {
    render(<SnippetText text="python" highlights={[{ start: 0, end: 999 }]} />);

    const mark = screen.getByText("python");
    expect(mark.tagName).toBe("MARK");
    expect(mark.textContent).toBe("python");
  });

  it("clamps a highlight with a negative start to the beginning of the text", () => {
    render(<SnippetText text="python" highlights={[{ start: -5, end: 3 }]} />);

    const mark = screen.getByText("pyt");
    expect(mark.tagName).toBe("MARK");
  });

  it("drops a highlight range entirely when start >= end after clamping", () => {
    // start=10, end=2 en un texto de 6 caracteres: tras el clamp, start > end,
    // así que no debe crashear ni producir un <mark> vacío o invertido.
    render(<SnippetText text="python" highlights={[{ start: 10, end: 2 }]} />);

    expect(document.querySelectorAll("mark")).toHaveLength(0);
    expect(screen.getByText("python").tagName).toBe("P");
  });

  it("resolves overlapping ranges by keeping the earliest and clamping the rest", () => {
    render(
      <SnippetText
        text="python tutorial"
        highlights={[
          { start: 0, end: 6 }, // "python"
          { start: 3, end: 9 }, // solapa con el anterior en [3,6)
        ]}
      />,
    );

    // El segundo rango solapa con el primero; tras sanear debe quedar
    // recortado al tramo no cubierto ([6,9) = " tu"), no descartado ni
    // duplicando texto ya resaltado.
    const marks = document.querySelectorAll("mark");
    expect(marks).toHaveLength(2);
    expect(marks[0]?.textContent).toBe("python");
    expect(marks[1]?.textContent).toBe(" tu");
  });

  it("sorts unsorted highlight ranges before rendering", () => {
    render(
      <SnippetText
        text="uno dos tres"
        highlights={[
          { start: 8, end: 12 }, // "tres"
          { start: 0, end: 3 }, // "uno"
        ]}
      />,
    );

    const marks = document.querySelectorAll("mark");
    expect(marks).toHaveLength(2);
    expect(marks[0]?.textContent).toBe("uno");
    expect(marks[1]?.textContent).toBe("tres");
  });
});
