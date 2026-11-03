/**
 * The pager a dataset table uses. The row count is the dataset's own count, and the range
 * says which rows of that count the table shows now.
 */
export default function Pager({
  page,
  pageCount,
  from,
  to,
  total,
  onChange,
}: {
  page: number;
  pageCount: number;
  from: number;
  to: number;
  total: number;
  onChange: (page: number) => void;
}) {
  if (total === 0) return null;
  return (
    <div className="pager">
      <span className="fabric-meta">
        Showing {from}-{to} of {total}
      </span>
      <div className="pager-actions">
        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={() => onChange(page - 1)}
          disabled={page <= 0}
          aria-label="Previous page"
        >
          Previous
        </button>
        <span className="fabric-meta">
          Page {page + 1} of {pageCount}
        </span>
        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={() => onChange(page + 1)}
          disabled={page >= pageCount - 1}
          aria-label="Next page"
        >
          Next
        </button>
      </div>
    </div>
  );
}
