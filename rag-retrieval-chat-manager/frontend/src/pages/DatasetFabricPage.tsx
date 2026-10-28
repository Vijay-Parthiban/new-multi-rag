import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import PageHeader from "../components/PageHeader";
import {
  IconBucket,
  IconChevronRight,
  IconClose,
  IconEdit,
  IconFile,
  IconPlus,
  IconRefresh,
  IconTrash,
  IconUpload,
} from "../components/Icons";
import {
  createDatasetProfile,
  DatasetKind,
  DatasetPreview,
  DatasetProfile,
  DatasetProfileFile,
  deleteDatasetProfile,
  deleteProfileDataset,
  listDatasetProfiles,
  listPipelines,
  PipelineRecord,
  previewProfileDataset,
  updateDatasetProfile,
  uploadProfileDataset,
} from "../api";
import { formatRelativeTime } from "../utils/format";

// The formats the server accepts. The picker filters to them and the route refuses anything
// else, so a wrong file never reaches the parser.
const ACCEPT = ".csv,.json,.jsonl,.xlsx,.parquet";

const KIND_LABEL: Record<DatasetKind, string> = {
  single_turn: "Single-turn",
  multi_turn: "Multi-turn",
};

const KIND_HINT: Record<DatasetKind, string> = {
  single_turn: "One question and answer per row.",
  multi_turn: "Conversations with follow-ups, replayed through session memory.",
};

const EMPTY_HINT: Record<DatasetKind, string> = {
  single_turn: "Upload a CSV, JSON, JSONL, XLSX or Parquet of questions and answers.",
  multi_turn: "Upload the same formats with a turns array on each row.",
};

/** The value the pipeline select carries for "yet to be linked". */
const UNLINKED = "";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export default function DatasetFabricPage() {
  const navigate = useNavigate();
  const [profiles, setProfiles] = useState<DatasetProfile[]>([]);
  const [pipelines, setPipelines] = useState<PipelineRecord[]>([]);
  const [profileId, setProfileId] = useState<string | null>(null);
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [uploadingKind, setUploadingKind] = useState<DatasetKind | null>(null);
  // A page-level failure: loading, creating, deleting.
  const [error, setError] = useState<string | null>(null);
  // A result beside the uploads, where the action happened.
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  // The create and edit form share one panel; `editingId` says which profile it edits.
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const viewerRef = useRef<HTMLElement | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [pipelineSlug, setPipelineSlug] = useState<string>(UNLINKED);
  const singleInput = useRef<HTMLInputElement | null>(null);
  const multiInput = useRef<HTMLInputElement | null>(null);
  const nameInput = useRef<HTMLInputElement | null>(null);

  const selected = useMemo(
    () => profiles.find((p) => p.id === profileId) ?? null,
    [profiles, profileId],
  );

  const byKind = useMemo(() => {
    const map: Record<DatasetKind, DatasetProfileFile[]> = { single_turn: [], multi_turn: [] };
    for (const file of selected?.datasets ?? []) {
      (map[file.kind] ?? map.single_turn).push(file);
    }
    return map;
  }, [selected]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextProfiles, nextPipelines] = await Promise.all([
        listDatasetProfiles(),
        listPipelines().catch(() => [] as PipelineRecord[]),
      ]);
      setProfiles(nextProfiles);
      setPipelines(nextPipelines);
      setProfileId((prev) => {
        if (prev && nextProfiles.some((p) => p.id === prev)) return prev;
        return nextProfiles[0]?.id ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the dataset profiles");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (formOpen) nameInput.current?.focus();
  }, [formOpen]);

  // The viewer opens below the grid, so bring it into view without a jump.
  useEffect(() => {
    if (!preview) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    viewerRef.current?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  }, [preview]);

  function resetForm() {
    setName("");
    setDescription("");
    setPipelineSlug(UNLINKED);
  }

  function closeForm() {
    setFormOpen(false);
    setEditingId(null);
    setError(null);
    resetForm();
  }

  function openCreate() {
    setEditingId(null);
    resetForm();
    setError(null);
    setFormOpen(true);
  }

  function openEdit(profile: DatasetProfile) {
    setEditingId(profile.id);
    setName(profile.name);
    setDescription(profile.description ?? "");
    setPipelineSlug(profile.pipeline_slug ?? UNLINKED);
    setError(null);
    setNotice(null);
    setFormOpen(true);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const nextName = name.trim();
    if (!nextName) {
      setError("Give the profile a name.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (editingId) {
        // The route reads null as "leave as is", so an empty string clears a field.
        await updateDatasetProfile(editingId, {
          name: nextName,
          description: description.trim(),
          pipeline_slug: pipelineSlug,
        });
        await load();
        setProfileId(editingId);
        setNotice({ kind: "ok", text: "Saved the profile." });
      } else {
        const created = await createDatasetProfile({
          name: nextName,
          description: description.trim() || null,
          pipeline_slug: pipelineSlug || null,
        });
        await load();
        setProfileId(created.id);
        setPreview(null);
        setNotice(null);
      }
      closeForm();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : editingId
            ? "Could not save the profile"
            : "Could not create the profile",
      );
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteProfile() {
    if (!selected) return;
    if (!window.confirm(`Delete '${selected.name}' and every dataset in it?`)) return;
    setBusy(true);
    try {
      await deleteDatasetProfile(selected.id);
      setPreview(null);
      setNotice(null);
      if (editingId === selected.id) closeForm();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the profile");
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(kind: DatasetKind, file: File | undefined) {
    if (!selected || !file) return;
    setUploadingKind(kind);
    setError(null);
    setNotice(null);
    try {
      const uploaded = await uploadProfileDataset(selected.id, file, kind);
      await load();
      setPreview(null);
      setNotice({
        kind: "ok",
        text: `Uploaded ${uploaded.row_count ?? "?"} row${
          uploaded.row_count === 1 ? "" : "s"
        } into ${KIND_LABEL[kind].toLowerCase()}.`,
      });
    } catch (err) {
      setNotice({
        kind: "error",
        text: err instanceof Error ? err.message : "Could not upload the dataset",
      });
    } finally {
      setUploadingKind(null);
    }
  }

  async function onOpen(file: DatasetProfileFile) {
    if (!selected) return;
    setError(null);
    try {
      setPreview(await previewProfileDataset(selected.id, file.dataset_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open the dataset");
    }
  }

  async function onDeleteFile(file: DatasetProfileFile) {
    if (!selected) return;
    if (!window.confirm(`Delete '${file.filename ?? file.dataset_id}'? Its runs are removed too.`)) {
      return;
    }
    try {
      await deleteProfileDataset(selected.id, file.dataset_id);
      if (preview?.dataset_id === file.dataset_id) setPreview(null);
      setNotice({ kind: "ok", text: `Deleted ${file.filename ?? "the dataset"}.` });
      await load();
    } catch (err) {
      setNotice({
        kind: "error",
        text: err instanceof Error ? err.message : "Could not delete the dataset",
      });
    }
  }

  const linkedLabel = (profile: DatasetProfile) =>
    profile.pipeline_name || profile.pipeline_slug || "";

  return (
    <>
      <PageHeader
        title="Dataset Fabric"
        description="One profile per evaluation purpose. Link it to a pipeline, or leave it unlinked and link it later."
        breadcrumbs={[
          { label: "Overview", to: "/" },
          { label: "Dataset Fabric", to: "/dataset-fabric" },
        ]}
        actions={
          <>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => void load()}
              disabled={loading}
              title="Reload profiles"
            >
              <IconRefresh size={15} />
              Refresh
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                if (formOpen) {
                  closeForm();
                } else {
                  openCreate();
                }
              }}
              aria-expanded={formOpen}
            >
              {formOpen ? <IconClose size={15} /> : <IconPlus size={15} />}
              {formOpen ? "Cancel" : "New profile"}
            </button>
          </>
        }
      />

      {error && (
        <div className="alert alert-error" style={{ marginBottom: "1rem" }}>
          {error}
        </div>
      )}

      {formOpen && (
        <div className="panel" style={{ marginBottom: "1rem" }}>
          <div className="panel-header">
            <h3 className="panel-title">{editingId ? "Edit profile" : "New profile"}</h3>
            <span className="fabric-meta">
              A profile holds the datasets graded against one pipeline.
            </span>
          </div>
          <form className="fabric-create" onSubmit={(e) => void onSubmit(e)}>
            <div className="form-row">
              <div>
                <label className="field-label" htmlFor="fabric-name">
                  Profile name
                </label>
                <input
                  id="fabric-name"
                  ref={nameInput}
                  className="input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Resume screening"
                  maxLength={128}
                  required
                />
              </div>
              <div>
                <label className="field-label" htmlFor="fabric-pipeline">
                  RAG pipeline
                </label>
                <select
                  id="fabric-pipeline"
                  className="input"
                  value={pipelineSlug}
                  onChange={(e) => setPipelineSlug(e.target.value)}
                >
                  <option value={UNLINKED}>Yet to be linked with a RAG pipeline</option>
                  {pipelines.map((p) => (
                    <option key={p.id} value={p.slug ?? ""}>
                      {p.name} · {p.rag_strategy}
                    </option>
                  ))}
                </select>
                <p className="field-hint" style={{ margin: "0.375rem 0 0" }}>
                  Linked writes into that pipeline's Knowledge Product bucket. Unlinked writes
                  into the shared <code>dataset-fabric</code> bucket.
                </p>
              </div>
            </div>
            <div>
              <label className="field-label" htmlFor="fabric-description">
                Description
              </label>
              <textarea
                id="fabric-description"
                className="input"
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What this profile is for, and what a good score means."
                style={{ resize: "vertical", fontFamily: "inherit" }}
              />
            </div>
            <div className="fabric-create-actions">
              <button type="button" className="btn btn-ghost" onClick={closeForm}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={busy}>
                {busy ? "Saving…" : editingId ? "Save changes" : "Create profile"}
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="fabric-grid">
        {/* ── Profiles ─────────────────────────────────────────────── */}
        <div className="panel">
          <div className="panel-header">
            <h3 className="panel-title">Profiles</h3>
            <span className="fabric-meta">
              {profiles.length} {profiles.length === 1 ? "profile" : "profiles"}
            </span>
          </div>

          {loading ? (
            <p className="panel-empty muted">Loading…</p>
          ) : profiles.length === 0 ? (
            <div className="panel-empty">
              <IconBucket size={28} className="muted" />
              <p className="muted" style={{ margin: 0 }}>
                No profiles yet. A profile groups the datasets for one purpose.
              </p>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={openCreate}
              >
                <IconPlus size={14} />
                Create the first profile
              </button>
            </div>
          ) : (
            <div className="fabric-list">
              {profiles.map((profile) => {
                const active = profile.id === profileId;
                const counts = { single_turn: 0, multi_turn: 0 } as Record<DatasetKind, number>;
                for (const file of profile.datasets) counts[file.kind] += 1;
                return (
                  <button
                    key={profile.id}
                    type="button"
                    className={`fabric-profile${active ? " fabric-profile--active" : ""}`}
                    aria-current={active ? "true" : undefined}
                    onClick={() => {
                      setProfileId(profile.id);
                      setPreview(null);
                      setNotice(null);
                      if (editingId && editingId !== profile.id) closeForm();
                    }}
                  >
                    <span className="fabric-avatar" aria-hidden="true">
                      {initials(profile.name)}
                    </span>
                    <span style={{ display: "grid", gap: "0.15rem", minWidth: 0, flex: 1 }}>
                      <span className="fabric-name fabric-ellipsis">{profile.name}</span>
                      <span
                        style={{
                          display: "flex",
                          gap: "0.35rem",
                          alignItems: "center",
                          flexWrap: "wrap",
                        }}
                      >
                        <span
                          className={`fabric-chip${profile.pipeline_slug ? " fabric-chip--linked" : ""}`}
                        >
                          {profile.pipeline_slug ? linkedLabel(profile) : "Unlinked"}
                        </span>
                        <span className="fabric-meta">
                          {counts.single_turn} single-turn · {counts.multi_turn} multi-turn
                        </span>
                      </span>
                      {profile.description && (
                        <span className="fabric-meta fabric-ellipsis">{profile.description}</span>
                      )}
                    </span>
                    <IconChevronRight size={14} className="muted" />
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Workspace ────────────────────────────────────────────── */}
        {selected ? (
          <div style={{ display: "grid", gap: "1rem", minWidth: 0 }}>
            <div className="panel">
              <div className="panel-header" style={{ alignItems: "flex-start", gap: "0.75rem" }}>
                <div style={{ display: "grid", gap: "0.2rem", minWidth: 0 }}>
                  <h3 className="panel-title" style={{ fontSize: "1rem" }}>
                    {selected.name}
                  </h3>
                  <span className="fabric-meta">
                    {selected.pipeline_slug
                      ? `Linked to ${linkedLabel(selected)}`
                      : "Yet to be linked with a RAG pipeline"}
                    {selected.knowledge_product_name
                      ? ` · ${selected.knowledge_product_name}`
                      : ""}
                  </span>
                </div>
                <div style={{ display: "flex", gap: "0.5rem", flex: "none" }}>
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    onClick={() => openEdit(selected)}
                    title="Edit this profile"
                  >
                    <IconEdit size={13} />
                    Edit
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    onClick={() => navigate("/golden-evaluations")}
                    title="Open Offline Evaluation"
                  >
                    Evaluate
                    <IconChevronRight size={13} />
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-danger"
                    onClick={() => void onDeleteProfile()}
                    disabled={busy}
                  >
                    <IconTrash size={13} />
                    Delete
                  </button>
                </div>
              </div>

              {selected.description && (
                <p className="field-hint" style={{ margin: 0, padding: "0.75rem 1rem 0" }}>
                  {selected.description}
                </p>
              )}
              {notice && (
                <p
                  role="status"
                  style={{
                    margin: 0,
                    padding: "0.5rem 1rem 0",
                    fontSize: "0.8rem",
                    color: notice.kind === "ok" ? "var(--success-text)" : "var(--danger)",
                  }}
                >
                  {notice.text}
                </p>
              )}

              <div className="fabric-cards">
                {(Object.keys(KIND_LABEL) as DatasetKind[]).map((kind) => {
                  const files = byKind[kind];
                  const uploading = uploadingKind === kind;
                  const inputRef = kind === "single_turn" ? singleInput : multiInput;
                  return (
                    <div className="fabric-card" key={kind}>
                      <div className="fabric-card-head">
                        <div style={{ display: "grid", gap: "0.1rem", flex: 1, minWidth: 0 }}>
                          <strong style={{ fontSize: "0.875rem" }}>{KIND_LABEL[kind]}</strong>
                          <span className="fabric-meta">{KIND_HINT[kind]}</span>
                        </div>
                        <span className="fabric-chip">
                          {files.length} {files.length === 1 ? "file" : "files"}
                        </span>
                        <label
                          className={`btn btn-sm ${files.length === 0 ? "btn-primary" : "btn-secondary"}`}
                          style={{
                            cursor: uploading ? "default" : "pointer",
                            margin: 0,
                            flex: "none",
                            opacity: uploading ? 0.7 : 1,
                          }}
                        >
                          <IconUpload size={13} />
                          {uploading ? "Uploading…" : "Upload"}
                          <input
                            ref={inputRef}
                            type="file"
                            accept={ACCEPT}
                            style={{ display: "none" }}
                            disabled={uploading}
                            aria-label={`Upload a ${KIND_LABEL[kind].toLowerCase()} dataset`}
                            onChange={(e) => {
                              const file = e.target.files?.[0];
                              // Clear the input so choosing the same file again fires onChange.
                              e.target.value = "";
                              void onUpload(kind, file);
                            }}
                          />
                        </label>
                      </div>

                      <div className="fabric-card-body">
                        {files.length === 0 ? (
                          <div className="fabric-empty">
                            No {KIND_LABEL[kind].toLowerCase()} dataset yet.
                            <br />
                            {EMPTY_HINT[kind]}
                          </div>
                        ) : (
                          <ul className="fabric-files">
                            {files.map((file) => (
                              <li key={file.dataset_id} className="fabric-file">
                                <IconFile size={16} className="muted" />
                                <button
                                  type="button"
                                  className="fabric-file-main"
                                  onClick={() => void onOpen(file)}
                                  aria-label={`View ${file.filename ?? "dataset"}`}
                                >
                                  <span className="fabric-file-name">
                                    {file.filename ?? "dataset"}
                                  </span>
                                  <span className="fabric-meta">
                                    {file.row_count ?? "?"}{" "}
                                    {file.row_count === 1 ? "row" : "rows"} · {file.format ?? "?"} ·{" "}
                                    {file.created_at
                                      ? formatRelativeTime(file.created_at)
                                      : "just now"}
                                  </span>
                                </button>
                                <span className="fabric-file-actions">
                                  <button
                                    type="button"
                                    className="btn btn-sm btn-ghost"
                                    onClick={() => void onOpen(file)}
                                  >
                                    View
                                  </button>
                                  <button
                                    type="button"
                                    className="btn btn-sm btn-ghost"
                                    onClick={() => void onDeleteFile(file)}
                                    aria-label={`Delete ${file.filename ?? "dataset"}`}
                                    title="Delete"
                                  >
                                    <IconTrash size={13} />
                                  </button>
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

          </div>
        ) : (
          <div className="panel">
            <div className="panel-empty">
              <IconBucket size={28} className="muted" />
              <p className="muted" style={{ margin: 0 }}>
                Select a profile to see its uploads.
              </p>
            </div>
          </div>
        )}
      </div>

      {preview && (
        <section
          className="panel fabric-viewer"
          ref={viewerRef}
          aria-labelledby="fabric-viewer-title"
        >
          <div className="panel-header fabric-viewer-head">
            <div style={{ display: "grid", gap: "0.3rem", minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                <IconFile size={16} className="muted" />
                <h3
                  className="panel-title"
                  id="fabric-viewer-title"
                  style={{ fontSize: "0.95rem", margin: 0 }}
                >
                  {preview.filename ?? "Dataset"}
                </h3>
                <span className="fabric-chip">{KIND_LABEL[preview.kind]}</span>
              </div>
              <span className="fabric-meta">
                {preview.items.length} {preview.items.length === 1 ? "row" : "rows"} shown
                {preview.row_count !== null && preview.row_count !== preview.items.length
                  ? ` of ${preview.row_count}`
                  : ""}
                {preview.bucket ? ` · ${preview.bucket}` : ""}
              </span>
            </div>
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={() => setPreview(null)}
              aria-label="Close the dataset viewer"
            >
              <IconClose size={13} />
              Close
            </button>
          </div>

          {preview.items.length === 0 ? (
            <p className="panel-empty muted">This dataset holds no rows.</p>
          ) : (
            <div className="fabric-viewer-scroll">
              <table className="fabric-table">
                <colgroup>
                  <col style={{ width: "7%" }} />
                  <col style={{ width: "30%" }} />
                  <col style={{ width: "37%" }} />
                  <col style={{ width: "16%" }} />
                  <col style={{ width: "10%" }} />
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col" className="fabric-th-num">
                      #
                    </th>
                    <th scope="col">Question</th>
                    <th scope="col">Ground truth</th>
                    <th scope="col">Type</th>
                    <th scope="col" className="fabric-th-num">
                      Sources
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {preview.items.map((item, index) => {
                    const category =
                      typeof item.metadata?.question_type === "string"
                        ? String(item.metadata.question_type).replace(/_/g, " ")
                        : "";
                    return (
                      <tr key={index}>
                        <td className="fabric-td-num">{index + 1}</td>
                        <td className="fabric-cell">{item.question || "—"}</td>
                        <td className="fabric-cell fabric-cell--muted">
                          {item.ground_truth_answer || "—"}
                        </td>
                        <td className="fabric-cell fabric-cell--muted">
                          <span className="fabric-type">
                            {item.turns
                              ? `${item.turns.length} turn${item.turns.length === 1 ? "" : "s"}`
                              : "Single"}
                          </span>
                          {category && <span className="fabric-meta">{category}</span>}
                        </td>
                        <td className="fabric-td-num">
                          {item.expected_sources.length > 0 ? item.expected_sources.length : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  );
}
