import type { ShardStatusInfo } from "../types/api";

interface ShardStatusBannerProps {
  message: string | null;
  shardStatuses: ShardStatusInfo[];
}

const STATUS_LABELS: Record<string, string> = {
  ok: "en línea",
  timeout: "sin respuesta (timeout)",
  error: "error",
};

/** Degradación explícita, nunca silenciosa: si algún shard del índice no
 * respondió, se muestra qué nodos fallaron y que los resultados son parciales
 * (los que devolvieron los shards sanos). */
export function ShardStatusBanner({ message, shardStatuses }: ShardStatusBannerProps) {
  const failed = shardStatuses.filter((shard) => shard.status !== "ok");
  return (
    <div className="degraded-banner" role="alert">
      <strong>Índice degradado.</strong>{" "}
      {message ?? "Parte de los nodos del índice no respondió a tiempo."}
      <ul>
        {shardStatuses.map((shard) => (
          <li key={shard.shard_id} className={shard.status === "ok" ? "shard-ok" : "shard-down"}>
            shard {shard.shard_id}: {STATUS_LABELS[shard.status] ?? shard.status}
            {shard.error_message ? ` — ${shard.error_message}` : ""}
          </li>
        ))}
      </ul>
      {failed.length < shardStatuses.length && (
        <p className="degraded-note">
          Los resultados mostrados provienen únicamente de los shards en línea.
        </p>
      )}
    </div>
  );
}
