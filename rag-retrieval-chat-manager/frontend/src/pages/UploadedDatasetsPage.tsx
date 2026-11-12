import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import PageHeader from "../components/PageHeader";
import RowDrawer, { sourceLabel } from "../components/RowDrawer";
import Pager from "../components/Pager";
import StatusBadge from "../components/StatusBadge";
import {
  IconChevronRight,
  IconPlus,
  IconRefresh,
  IconTrash,
  IconUpload,
} from "../components/Icons";
import {
  activateUploadedVersion,
  createUploadedProfile,
  createUploadedVersion,
  deleteUploadedProfile,
  deleteUploadedVersion,
  deleteVersionDataset,
  getUploadedProfile,
  listKnowledgeProducts,
  listUploadedProfiles,
  listUploadedVersionItems,
  uploadVersionDataset,
  type KnowledgeProduct,
  type SyntheticDatasetKind,
  type SyntheticProfileDetail,
  type SyntheticVersion,
  type SyntheticVersionItem,
  type UploadedProfile,
} from "../api";
import { rowQuestionTypes } from "../questionTypes";
import { formatRelativeTime } from "../utils/format";

const KINDS: SyntheticDatasetKind[] = ["single_turn", "multi_turn"];
const KIND_LABEL: Record<SyntheticDatasetKind, string> = {
  single_turn: "Single-turn",
  multi_turn: "Multi-turn",
};
const ACCEPT = ".csv,.json,.jsonl,.xlsx,.parquet";
const PAGE_SIZE = 20;

/** One file per dataset kind, chosen but not yet sent. */
type Picks = Partial<Record<SyntheticDatasetKind, File>>;

/**
 * Uploaded Datasets: manual profiles, their versions, and the files a version holds.
 *
 * Same shape as the Synthetic Dataset Creator, from the other author. A profile belongs to
 * one Knowledge Product, a version is a numbered slot, and each version holds at most one
 * single-turn and one multi-turn dataset. The active profile and the active version are
 * stored per source, so this page's toggle never touches the synthetic one.
 */
export default function UploadedDatasetsPage() {
  const [profiles, setProfiles] = useState<UploadedProfile[]>([]);
  const [products, setProducts] = useState<KnowledgeProduct[]>([]);
  const [productId, setProductId] = useState("");
  const [profileId, setProfileId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SyntheticProfileDetail | null>(null);
  const [versionId, setVersionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [busyKind, setBusyKind] = useState<SyntheticDatasetKind | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [profileFormOpen, setProfileFormOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");

  const [creatorOpen, setCreatorOpen] = useState(false);
  const [newVersionNo, setNewVersionNo] = useState("");
  const [newVersionDescription, setNewVersionDescription] = useState("");

  const [picks, setPicks] = useState<Picks>({});
  const [rowsKind, setRowsKind] = useState<SyntheticDatasetKind | null>(null);
  const [rows, setRows] = useState<SyntheticVersionItem[]>([]);
  const [rowCount, setRowCount] = useState(0);
  const [detailRow, setDetailRow] = useState<{
    item: SyntheticVersionItem;
    position: number;
  } | null>(null);
  const [page, setPage] = useState(0);

  const versionRef = useRef<HTMLElement | null>(null);

  const profilesForProduct = useMemo(
    () => profiles.filter((item) => item.knowledge_product_id === productId),
    [profiles, productId],
  );
  const profile =
    detail?.profile ?? profiles.find((item) => item.id === profileId) ?? null;
  const version = detail?.versions.find((item) => item.id === versionId) ?? null;
  const nextVersionNo = (detail?.versions[0]?.version_no ?? 0) + 1;

  const loadProfiles = useCallback(async () => {
    const next = await listUploadedProfiles();
    setProfiles(next);
    return next;
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    const next = await getUploadedProfile(id);
    setDetail(next);
    return next;
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const [nextProfiles, nextProducts] = await Promise.all([
          listUploadedProfiles(),
          listKnowledgeProducts(),
        ]);
        setProfiles(nextProfiles);
        setProducts(nextProducts);
        setProductId((prev) => prev || nextProfiles[0]?.knowledge_product_id || nextProducts[0]?.id || "");
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : String(exc));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!versionId || !rowsKind) return;
    let alive = true;
    void (async () => {
      try {
        const res = await listUploadedVersionItems(
          versionId,
          rowsKind,
          page * PAGE_SIZE,
          PAGE_SIZE,
        );
        if (!alive) return;
        setRows(res.items);
        setRowCount(res.count);
      } catch (exc) {
        if (alive) setError(exc instanceof Error ? exc.message : String(exc));
      }
    })();
    return () => {
      alive = false;
    };
  }, [versionId, rowsKind, page]);

  useEffect(() => {
    if (version) versionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [version?.id]);

  const resetVersionView = () => {
    setVersionId(null);
    setRowsKind(null);
    setRows([]);
    setRowCount(0);
    setPage(0);
    setPicks({});
  };

  const openProfile = async (id: string) => {
    setBusy(true);
    setError(null);
    setPicks({});
    setRowsKind(null);
    try {
      const next = await loadDetail(id);
      setProfileId(id);
      setVersionId(next.versions[0]?.id ?? null);
      setCreatorOpen(next.versions.length === 0);
      setProfileFormOpen(false);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const backToProfiles = () => {
    setProfileId(null);
    setDetail(null);
    resetVersionView();
    setCreatorOpen(false);
  };

  const refresh = async () => {
    setBusy(true);
    setError(null);
    try {
      await loadProfiles();
      if (profileId) await loadDetail(profileId);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const onCreateProfile = async (event: FormEvent) => {
    event.preventDefault();
    if (!productId) {
      setError("Pick a Knowledge Product first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await createUploadedProfile({
        name: newName.trim(),
        description: newDescription.trim() || null,
        knowledge_product_id: productId,
      });
      setNewName("");
      setNewDescription("");
      setProfileFormOpen(false);
      await loadProfiles();
      await openProfile(created.id);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const onCreateVersion = async (event: FormEvent) => {
    event.preventDefault();
    if (!profileId) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createUploadedVersion(profileId, {
        version_no: newVersionNo ? Number(newVersionNo) : undefined,
        description: newVersionDescription.trim() || null,
      });
      setNewVersionNo("");
      setNewVersionDescription("");
      setCreatorOpen(false);
      const next = await loadDetail(profileId);
      setProfiles((prev) =>
        prev.map((item) =>
          item.id === profileId ? { ...item, version_count: next.versions.length } : item,
        ),
      );
      setVersionId(created.id);
      setPicks({});
      setRowsKind(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const onActivateVersion = async (row: SyntheticVersion) => {
    setBusy(true);
    setError(null);
    try {
      await activateUploadedVersion(row.id);
      if (profileId) await loadDetail(profileId);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const onDeleteProfile = async () => {
    if (!profile) return;
    if (
      !window.confirm(
        `Delete the profile "${profile.name}"? Delete its versions first if it has any.`,
      )
    )
      return;
    setBusy(true);
    setError(null);
    try {
      await deleteUploadedProfile(profile.id);
      backToProfiles();
      await loadProfiles();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const onDeleteVersion = async (row: SyntheticVersion) => {
    if (!window.confirm(`Delete version ${row.version_no} and the files it holds?`)) return;
    setBusy(true);
    setError(null);
    try {
      await deleteUploadedVersion(row.id);
      if (versionId === row.id) resetVersionView();
      if (profileId) {
        const next = await loadDetail(profileId);
        setProfiles((prev) =>
          prev.map((item) =>
            item.id === profileId ? { ...item, version_count: next.versions.length } : item,
          ),
        );
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const onPick = (kind: SyntheticDatasetKind, event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setPicks((prev) => ({ ...prev, [kind]: file }));
  };

  const onUpload = async (kind: SyntheticDatasetKind) => {
    const file = picks[kind];
    if (!file || !versionId) return;
    setBusyKind(kind);
    setError(null);
    try {
      const updated = await uploadVersionDataset(versionId, file, kind);
      setDetail((prev) =>
        prev
          ? {
              ...prev,
              versions: prev.versions.map((item) =>
                item.id === updated.id ? updated : item,
              ),
            }
          : prev,
      );
      setPicks((prev) => ({ ...prev, [kind]: undefined }));
      if (rowsKind === kind) setPage(0);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusyKind(null);
    }
  };

  const onDeleteDataset = async (kind: SyntheticDatasetKind) => {
    if (!versionId) return;
    if (!window.confirm(`Delete the ${KIND_LABEL[kind].toLowerCase()} dataset and its rows?`))
      return;
    setBusy(true);
    setError(null);
    try {
      await deleteVersionDataset(versionId, kind);
      if (rowsKind === kind) {
        setRowsKind(null);
        setRows([]);
        setRowCount(0);
      }
      if (profileId) await loadDetail(profileId);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const viewRows = (kind: SyntheticDatasetKind) => {
    setRowsKind(kind);
    setPage(0);
    setRows([]);
    setDetailRow(null);
  };

  const renderSlot = (kind: SyntheticDatasetKind) => {
    const dataset = version?.datasets.find((item) => item.kind === kind);
    const pick = picks[kind];
    const uploading = busyKind === kind;

    return (
      <section className="sd-slot" key={kind}>
        <div className="sd-slot-head">
          <h3 className="sd-pane-title">{KIND_LABEL[kind]} dataset</h3>
          {dataset ? (
            <StatusBadge status="completed" />
          ) : (
            <span className="fabric-meta">Not uploaded</span>
          )}
        </div>

        <div className="sd-slot-body">
          {dataset ? (
            <dl className="sd-facts">
              <div>
                <dt>Rows</dt>
                <dd>{dataset.row_count ?? 0}</dd>
              </div>
              <div>
                <dt>File</dt>
                <dd className="sd-file-name">{dataset.original_filename ?? "—"}</dd>
              </div>
              <div>
                <dt>Uploaded</dt>
                <dd>{dataset.created_at ? formatRelativeTime(dataset.created_at) : "—"}</dd>
              </div>
              <div>
                <dt>Fabric</dt>
                <dd>{profile?.fabric_profile_name ?? "—"}</dd>
              </div>
            </dl>
          ) : (
            <p className="muted sd-slot-hint">
              Upload one file of {KIND_LABEL[kind].toLowerCase()} rows.
            </p>
          )}

          <input
            className="sd-file"
            id={`sd-file-${kind}`}
            type="file"
            accept={ACCEPT}
            title="CSV, JSON, JSONL, XLSX or Parquet"
            aria-label={`${dataset ? "Replace" : "Upload"} ${KIND_LABEL[
              kind
            ].toLowerCase()} dataset file`}
            onChange={(event) => onPick(kind, event)}
            disabled={uploading}
          />

          <div className="sd-slot-actions">
            <button
              type="button"
              className={`btn btn-sm ${dataset ? "btn-secondary" : "btn-primary"}`}
              onClick={() => void onUpload(kind)}
              disabled={!pick || uploading}
            >
              <IconUpload size={14} />
              {uploading ? "Uploading..." : dataset ? "Replace dataset" : "Upload dataset"}
            </button>
            {dataset && (
              <>
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  onClick={() => viewRows(kind)}
                >
                  View rows
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-danger-ghost"
                  onClick={() => void onDeleteDataset(kind)}
                  disabled={busy || uploading}
                >
                  <IconTrash size={14} />
                  Delete
                </button>
              </>
            )}
          </div>
        </div>
      </section>
    );
  };

  return (
    <div className="page">
      <PageHeader
        title="Uploaded Datasets"
        description="Pick a Knowledge Product, then keep one active version in each manual profile. A version holds a single-turn file and a multi-turn file that you upload."
        breadcrumbs={[
          { label: "Overview", to: "/" },
          { label: "Uploaded Datasets", to: "/uploaded-datasets" },
        ]}
        actions={
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => void refresh()}
            disabled={busy}
          >
            <IconRefresh size={14} />
            Refresh
          </button>
        }
      />

      {error && <p className="form-error">{error}</p>}

      {!profileId ? (
        <section className="sd-profiles">
          <div className="sd-product">
            <div className="sd-field">
              <label htmlFor="ud-product">Knowledge Product</label>
              <select
                className="input"
                id="ud-product"
                value={productId}
                onChange={(event) => {
                  setProductId(event.target.value);
                  setProfileFormOpen(false);
                }}
              >
                <option value="">Pick a product</option>
                {products.map((product) => (
                  <option key={product.id} value={product.id}>
                    {product.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="sd-profiles-head">
            <h2 className="sd-section-title">Manual profiles</h2>
            {productId && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => setProfileFormOpen((prev) => !prev)}
              >
                <IconPlus size={14} />
                New profile
              </button>
            )}
          </div>

          {profileFormOpen && (
            <form className="panel sd-form sd-form--wide" onSubmit={onCreateProfile}>
              <div className="sd-grid">
                <div className="sd-field">
                  <label htmlFor="ud-new-name">Name</label>
                  <input
                    className="input"
                    id="ud-new-name"
                    value={newName}
                    onChange={(event) => setNewName(event.target.value)}
                    placeholder="Résumé manual set"
                    required
                  />
                </div>
                <div className="sd-field">
                  <label htmlFor="ud-new-description">Description</label>
                  <input
                    className="input"
                    id="ud-new-description"
                    value={newDescription}
                    onChange={(event) => setNewDescription(event.target.value)}
                    placeholder="What these files cover"
                  />
                </div>
              </div>
              <div className="sd-form-actions">
                <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>
                  Create profile
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setProfileFormOpen(false)}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}

          {loading ? (
            <p className="muted">Loading...</p>
          ) : !productId ? (
            <p className="muted">Pick a Knowledge Product to see its manual profiles.</p>
          ) : profilesForProduct.length === 0 ? (
            <div className="panel panel-empty">
              <p className="muted" style={{ margin: 0 }}>
                No manual profile for this Knowledge Product yet.
              </p>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => setProfileFormOpen(true)}
              >
                <IconPlus size={14} />
                New profile
              </button>
            </div>
          ) : (
            <div className="sd-cards">
              {profilesForProduct.map((item) => (
                <div key={item.id} className="sd-card">
                  <span className="sd-card-name">{item.name}</span>
                  <span className="sd-card-kp">{item.description ?? "No description"}</span>
                  <span className="sd-card-kp">
                    Fabric profile · {item.fabric_profile_name ?? "none"}
                  </span>
                  <span className="sd-card-foot">
                    <span className="sd-card-count">
                      {item.version_count} {item.version_count === 1 ? "version" : "versions"}
                    </span>
                    <span className="sd-card-actions">
                      <button
                        type="button"
                        className="btn btn-sm btn-secondary"
                        onClick={() => void openProfile(item.id)}
                        disabled={busy}
                      >
                        Open
                      </button>
                    </span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      ) : (
        <>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            style={{ marginBottom: "0.75rem" }}
            onClick={backToProfiles}
          >
            <IconChevronRight size={14} className="sd-back-icon" />
            All profiles
          </button>

          <div className="sd-profile-head">
            <div>
              <h2 className="sd-section-title">{profile?.name ?? "Profile"}</h2>
              <p className="fabric-meta">
                {profile?.knowledge_product_name ?? profile?.knowledge_product_id} ·{" "}
                {profile?.description ?? "No description"}
              </p>
            </div>
            <div className="sd-header-actions">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => setCreatorOpen((prev) => !prev)}
                disabled={busy}
              >
                <IconPlus size={14} />
                New version
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => void onDeleteProfile()}
                disabled={busy}
                aria-label="Delete profile"
                title="Delete profile"
              >
                <IconTrash size={14} />
              </button>
            </div>
          </div>

          {creatorOpen && (
            <form className="panel sd-creator" onSubmit={onCreateVersion}>
              <div className="panel-header">
                <h3 className="panel-title">New version</h3>
                <span className="fabric-meta">Uploads arrive after creation</span>
              </div>
              <div className="sd-creator-body">
                <div className="sd-grid">
                  <div className="sd-field">
                    <label htmlFor="ud-version-no">Version no</label>
                    <input
                      className="input"
                      id="ud-version-no"
                      type="number"
                      min={1}
                      placeholder={String(nextVersionNo)}
                      value={newVersionNo}
                      onChange={(event) => setNewVersionNo(event.target.value)}
                    />
                  </div>
                  <div className="sd-field">
                    <label htmlFor="ud-version-description">Description</label>
                    <input
                      className="input"
                      id="ud-version-description"
                      value={newVersionDescription}
                      onChange={(event) => setNewVersionDescription(event.target.value)}
                      placeholder="Baseline questions"
                    />
                  </div>
                </div>
                <div className="sd-form-actions">
                  <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>
                    Create version
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => setCreatorOpen(false)}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </form>
          )}

          <div className="panel sd-versions">
            <div className="panel-header">
              <h3 className="panel-title">Versions</h3>
              <span className="fabric-meta">{detail?.versions.length ?? 0}</span>
            </div>
            {(detail?.versions.length ?? 0) === 0 ? (
              <p className="muted sd-empty">
                No version yet. Create one, then upload a file into it.
              </p>
            ) : (
              <table className="fabric-table">
                <thead>
                  <tr>
                    <th scope="col">Version</th>
                    <th scope="col">Datasets</th>
                    <th scope="col">Status</th>
                    <th scope="col">Created</th>
                    <th scope="col">Active</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(detail?.versions ?? []).map((row) => (
                    <tr
                      key={row.id}
                      className={versionId === row.id ? "sd-row-open" : undefined}
                      aria-current={versionId === row.id ? "true" : undefined}
                    >
                      <td>
                        <div className="sd-entry">
                          <span className="sd-num">v{row.version_no}</span>
                          {row.description && (
                            <span className="sd-entry-desc">{row.description}</span>
                          )}
                        </div>
                      </td>
                      <td>
                        <div className="sd-kinds">
                          {KINDS.map((kind) => {
                            const dataset = row.datasets.find((item) => item.kind === kind);
                            return (
                              <span
                                key={kind}
                                className={`sd-kind${dataset ? "" : " sd-kind--absent"}`}
                              >
                                {KIND_LABEL[kind].replace("-turn", "")}
                                {dataset ? ` ${dataset.row_count ?? 0}` : " —"}
                              </span>
                            );
                          })}
                        </div>
                      </td>
                      <td>
                        <StatusBadge status={row.status} />
                      </td>
                      <td>{row.created_at ? formatRelativeTime(row.created_at) : "—"}</td>
                      <td>
                        {row.is_active ? (
                          <StatusBadge status="active" />
                        ) : (
                          <button
                            type="button"
                            className="btn btn-sm btn-ghost"
                            onClick={() => void onActivateVersion(row)}
                            disabled={busy || row.datasets.length === 0}
                            title={
                              row.datasets.length === 0
                                ? "Upload a dataset first"
                                : undefined
                            }
                          >
                            Activate
                          </button>
                        )}
                      </td>
                      <td>
                        <div className="sd-row-actions">
                          <button
                            type="button"
                            className="btn btn-sm btn-secondary"
                            onClick={() => {
                              if (versionId === row.id) {
                                resetVersionView();
                              } else {
                                setVersionId(row.id);
                                setRowsKind(null);
                                setPicks({});
                              }
                            }}
                          >
                            {versionId === row.id ? "Close" : "View"}
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm btn-ghost"
                            onClick={() => void onDeleteVersion(row)}
                            disabled={busy}
                            aria-label={`Delete version ${row.version_no}`}
                            title={`Delete version ${row.version_no}`}
                          >
                            <IconTrash size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {version && (
            <section className="panel sd-version" ref={versionRef}>
              <div className="panel-header">
                <div className="sd-version-title">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={resetVersionView}
                    aria-label="Back to versions"
                    title="Back to versions"
                  >
                    <IconChevronRight size={14} className="sd-back-icon" />
                  </button>
                  <h3 className="panel-title sd-num">v{version.version_no}</h3>
                  {version.description && (
                    <span className="fabric-meta">{version.description}</span>
                  )}
                </div>
                {version.is_active ? (
                  <StatusBadge status="active" />
                ) : (
                  <button
                    type="button"
                    className="btn btn-sm btn-secondary"
                    onClick={() => void onActivateVersion(version)}
                    disabled={busy || version.datasets.length === 0}
                    title={
                      version.datasets.length === 0 ? "Upload a dataset first" : undefined
                    }
                  >
                    Activate version
                  </button>
                )}
              </div>

              <div className="sd-version-body">
                <div className="sd-panes sd-panes--divided">
                  {KINDS.map((kind) => renderSlot(kind))}
                </div>
              </div>

              {rowsKind && (
                <div className="sd-rows sd-rows--manual">
                  <div className="sd-rows-head">
                    <h3 className="panel-title">{KIND_LABEL[rowsKind]} rows</h3>
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost"
                      onClick={() => {
                        setRowsKind(null);
                        setRows([]);
                        setRowCount(0);
                        setDetailRow(null);
                      }}
                    >
                      Close
                    </button>
                  </div>
                  {rows.length === 0 ? (
                    <p className="sd-empty muted">No rows yet.</p>
                  ) : (
                    <div className="fabric-viewer-scroll">
                      <table className="fabric-table">
                        <thead>
                          <tr>
                            <th scope="col" className="fabric-th-num">
                              #
                            </th>
                            <th scope="col">Question</th>
                            <th scope="col">Ground truth</th>
                            <th scope="col" className="fabric-th-num">
                              Turns
                            </th>
                            <th scope="col">Sources</th>
                            <th scope="col">Question type</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((row, index) => {
                            const position = page * PAGE_SIZE + index + 1;
                            return (
                              <tr
                                key={row.id}
                                className="sd-row-click"
                                onClick={() => setDetailRow({ item: row, position })}
                              >
                                <td className="fabric-th-num">
                                  <button
                                    type="button"
                                    className="sd-row-index"
                                    aria-label={`Open row ${position}`}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      setDetailRow({ item: row, position });
                                    }}
                                  >
                                    {position}
                                  </button>
                                </td>
                                <td>
                                  <span className="sd-cell-clamp" title={row.question}>
                                    {row.question}
                                  </span>
                                </td>
                                <td>
                                  <span
                                    className="sd-cell-clamp"
                                    title={row.ground_truth_answer ?? ""}
                                  >
                                    {row.ground_truth_answer ?? "—"}
                                  </span>
                                </td>
                                <td className="fabric-th-num">{row.turns?.length ?? 1}</td>
                                <td>
                                  <span className="sd-cell-clamp">
                                    {(row.expected_sources ?? []).map(sourceLabel).join(", ") || "—"}
                                  </span>
                                </td>
                                <td>
                                  <span className="sd-cell-clamp">
                                    {rowQuestionTypes(row.metadata).join(", ") || "—"}
                                  </span>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <Pager
                    page={page}
                    pageCount={Math.max(1, Math.ceil(rowCount / PAGE_SIZE))}
                    from={page * PAGE_SIZE + 1}
                    to={Math.min(rowCount, (page + 1) * PAGE_SIZE)}
                    total={rowCount}
                    onChange={(next) => {
                      setPage(next);
                      setDetailRow(null);
                    }}
                  />
                </div>
              )}

              {detailRow && rowsKind && (
                <RowDrawer
                  item={detailRow.item}
                  position={detailRow.position}
                  kind={rowsKind}
                  onClose={() => setDetailRow(null)}
                />
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}
