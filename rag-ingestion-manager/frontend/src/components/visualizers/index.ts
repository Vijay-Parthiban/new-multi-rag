import type { ComponentType } from "react";
import type { DestinationInspectData } from "../../api";
import { CacheVisualizer } from "./CacheVisualizer";
import { LexicalVisualizer } from "./LexicalVisualizer";
import { RelationalVisualizer } from "./RelationalVisualizer";
import { VectorVisualizer } from "./VectorVisualizer";

export interface VisualizerEntry {
  label: string;
  engine: string;
  icon: string;
  color: string;
  Component: ComponentType<{ data: DestinationInspectData; loading: boolean }>;
}

/**
 * One entry per destination type the ingestion service supports.
 *
 * Adding a destination means one entry here plus one writer and one purger in
 * the backend fanout. The modal derives its tabs from this map, so no switch
 * statement needs touching.
 */
export const VISUALIZERS: Record<string, VisualizerEntry> = {
  vector_qdrant: {
    label: "Dense Vector Store",
    engine: "Qdrant",
    icon: "🌌",
    color: "#38bdf8",
    Component: VectorVisualizer,
  },
  lexical_opensearch: {
    label: "Sparse Vector Store",
    engine: "OpenSearch",
    icon: "🔍",
    color: "#818cf8",
    Component: LexicalVisualizer,
  },
  relational_pgvector: {
    label: "Relational Chunk Store",
    engine: "Postgres",
    icon: "🗄️",
    color: "#fbbf24",
    Component: RelationalVisualizer,
  },
  cache_redisvl: {
    label: "Cache Store",
    engine: "Redis VL",
    icon: "⚡",
    color: "#f472b6",
    Component: CacheVisualizer,
  },
};

export function visualizerFor(destinationType: string): VisualizerEntry | null {
  return VISUALIZERS[destinationType] ?? null;
}
