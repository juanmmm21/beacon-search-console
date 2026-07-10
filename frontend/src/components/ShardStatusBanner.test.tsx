import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { describe, expect, it } from "vitest";
import type { ShardStatusInfo } from "../types/api";
import { ShardStatusBanner } from "./ShardStatusBanner";

describe("ShardStatusBanner", () => {
  it("shows the message provided by the API", () => {
    const shardStatuses: ShardStatusInfo[] = [
      { shard_id: 0, status: "ok", error_message: null },
      { shard_id: 1, status: "timeout", error_message: "tiempo de espera agotado" },
    ];
    render(
      <ShardStatusBanner
        message="Resultados parciales: 1 de 2 nodos del índice no respondieron a tiempo."
        shardStatuses={shardStatuses}
      />,
    );

    expect(
      screen.getByText(/Resultados parciales: 1 de 2 nodos/),
    ).toBeInTheDocument();
  });

  it("falls back to a generic message when the API sends none", () => {
    render(
      <ShardStatusBanner
        message={null}
        shardStatuses={[{ shard_id: 0, status: "error", error_message: null }]}
      />,
    );

    expect(
      screen.getByText("Parte de los nodos del índice no respondió a tiempo."),
    ).toBeInTheDocument();
  });

  it("lists every shard with a human-readable, translated status label", () => {
    render(
      <ShardStatusBanner
        message="degradado"
        shardStatuses={[
          { shard_id: 0, status: "ok", error_message: null },
          { shard_id: 1, status: "timeout", error_message: null },
          { shard_id: 2, status: "error", error_message: "conexión rechazada" },
        ]}
      />,
    );

    expect(screen.getByText(/shard 0: en línea/)).toBeInTheDocument();
    expect(screen.getByText(/shard 1: sin respuesta \(timeout\)/)).toBeInTheDocument();
    expect(
      screen.getByText(/shard 2: error — conexión rechazada/),
    ).toBeInTheDocument();
  });

  it("shows an unrecognized status verbatim instead of hiding it", () => {
    render(
      <ShardStatusBanner
        message="degradado"
        shardStatuses={[{ shard_id: 3, status: "unknown_status", error_message: null }]}
      />,
    );

    expect(screen.getByText(/shard 3: unknown_status/)).toBeInTheDocument();
  });

  it("shows the healthy-shards note when at least one shard is still ok", () => {
    render(
      <ShardStatusBanner
        message="parcial"
        shardStatuses={[
          { shard_id: 0, status: "ok", error_message: null },
          { shard_id: 1, status: "timeout", error_message: null },
        ]}
      />,
    );

    expect(
      screen.getByText("Los resultados mostrados provienen únicamente de los shards en línea."),
    ).toBeInTheDocument();
  });

  it("omits the healthy-shards note when every shard has failed", () => {
    render(
      <ShardStatusBanner
        message="todo caído"
        shardStatuses={[
          { shard_id: 0, status: "error", error_message: null },
          { shard_id: 1, status: "timeout", error_message: null },
        ]}
      />,
    );

    expect(
      screen.queryByText("Los resultados mostrados provienen únicamente de los shards en línea."),
    ).not.toBeInTheDocument();
  });

  it("renders with an alert role so assistive tech announces degradation", () => {
    render(
      <ShardStatusBanner
        message="parcial"
        shardStatuses={[{ shard_id: 0, status: "timeout", error_message: null }]}
      />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("has no accessibility violations when reporting a degraded shard", async () => {
    const { container } = render(
      <ShardStatusBanner
        message="Resultados parciales: 1 de 3 nodos del índice no respondieron a tiempo."
        shardStatuses={[
          { shard_id: 0, status: "ok", error_message: null },
          { shard_id: 1, status: "timeout", error_message: "tiempo agotado" },
          { shard_id: 2, status: "error", error_message: "conexión rechazada" },
        ]}
      />,
    );

    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
