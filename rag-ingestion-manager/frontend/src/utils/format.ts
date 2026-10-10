export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
export const formatBytes = formatSize;

export function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  const diff = Date.now() - date.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return date.toLocaleDateString();
}

// Short display name for a chunk strategy, for the badges on the profile list and
// the product detail page. The long label and its hint come from the backend
// catalogue, which is what the profile form renders.
const CHUNK_STRATEGY_LABELS: Record<string, string> = {
  recursive: "Chunking: recursive",
  fixed: "Chunking: fixed size",
  section: "Chunking: structure aware",
  context_aware: "Chunking: semantic",
  parent_child: "Chunking: parent / child",
  contextual: "Chunking: contextual",
  page_level: "Chunking: page level",
  sentence_window: "Chunking: sentence window",
  // No longer offered in the form, but a profile saved earlier still holds one.
  sentence: "Chunking: sentence",
  layout: "Chunking: layout",
};

export function formatChunkStrategy(strategy: string): string {
  return CHUNK_STRATEGY_LABELS[strategy] || `Chunking: ${strategy}`;
}
