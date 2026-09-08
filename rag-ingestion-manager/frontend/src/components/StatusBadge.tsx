const LABELS: Record<string, string> = {
  processing: "Syncing",
  synced: "Synced",
  failed: "Failed",
  deleted: "Deleted",
  duplicate: "Duplicate",
  pending: "Pending",
  success: "Complete",
  completed: "Complete",
  running: "Running",
};

const ANIMATED = new Set(["processing", "running", "pending"]);

export default function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`status-badge status-${status}`}>
      {ANIMATED.has(status) && <span className="status-dot" />}
      {LABELS[status] ?? status}
    </span>
  );
}
