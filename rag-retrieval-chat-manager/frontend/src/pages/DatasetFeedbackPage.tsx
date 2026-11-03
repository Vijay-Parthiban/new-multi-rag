import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";

import PageHeader from "../components/PageHeader";
import MarkdownMessage from "../components/MarkdownMessage";
import Pager from "../components/Pager";
import {
  IconBucket,
  IconCheckCircle,
  IconChevronRight,
  IconClose,
  IconEdit,
  IconFile,
  IconPlus,
  IconRefresh,
  IconSearch,
} from "../components/Icons";
import {
  appendFeedbackRows,
  DatasetKind,
  DatasetPreview,
  DatasetPreviewItem,
  DatasetProfile,
  FeedbackConversation,
  FeedbackConversationDetail,
  FeedbackMode,
  getFeedbackConversation,
  listDatasetProfiles,
  listFeedbackConversations,
  previewProfileDataset,
  updateProfileDatasetItem,
} from "../api";
import { formatRelativeTime } from "../utils/format";

const PAGE_SIZE = 25;
// The dataset table pages at the size the Fabric viewer uses, so one row count reads the
// same on both pages.
const TRAY_PAGE_SIZE = 20;

const KIND_LABEL: Record<DatasetKind, string> = {
  single_turn: "Single-turn",
  multi_turn: "Multi-turn",
};

const KIND_HINT: Record<DatasetKind, string> = {
  single_turn: "A conversation with exactly one question.",
  multi_turn: "A conversation with follow-ups. The run replays your questions in order.",
};

const QUESTION_TYPES: Record<DatasetKind, string[]> = {
  single_turn: ["single_hop", "multi_hop", "comparative_cross_document", "edge_case", "out_of_corpus"],
  multi_turn: ["follow_up", "coreference", "multi_turn_multi_hop"],
};

const MODES: { value: FeedbackMode; label: string }[] = [
  { value: "all", label: "All" },
  { value: "test", label: "Test" },
  { value: "prod", label: "Prod" },
];

const SKIP_TEXT: Record<string, string> = {
  conversation_not_found: "That conversation is no longer available.",
  already_added: "Already in this dataset.",
  wrong_kind: "This conversation does not fit this dataset type.",
  answer_required: "Write the expected answer first.",
};

type Behavior = "answer_from_corpus" | "refuse_or_abstain";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

const modeLabel = (modes: string[]) =>
  modes.map((m) => (m === "test" ? "Test" : "Prod")).join(" + ");

const sourceName = (s: unknown) =>
  typeof s === "object" && s !== null && "name" in s ? String(s.name) : String(s);

type Turn = { role: string; content: string };

/**
 * One dataset row in a side panel.
 *
 * A row carries several related fields and the answer and the sources depend on the
 * expected behaviour, so it edits here with Save and Cancel, not in a table cell. Save
 * stays disabled until something changes, and Escape cancels.
 */
function RowEditor({
  item,
  kind,
  profileId,
  datasetId,
  onClose,
  onSaved,
}: {
  item: DatasetPreviewItem;
  kind: DatasetKind;
  profileId: string;
  datasetId: string;
  onClose: () => void;
  onSaved: (item: DatasetPreviewItem) => void;
}) {
  const isMulti = kind === "multi_turn";
  const [question, setQuestion] = useState(item.question);
  const [turns, setTurns] = useState<Turn[]>(
    () => (item.turns ?? []).map((t) => ({ role: t.role, content: t.content })),
  );
  const [answer, setAnswer] = useState(item.ground_truth_answer ?? "");
  const [sources, setSources] = useState(item.expected_sources.map(sourceName).join(", "));
  const [type, setType] = useState(
    typeof item.metadata?.question_type === "string" ? item.metadata.question_type : "",
  );
  const [behavior, setBehavior] = useState<Behavior>(
    item.metadata?.expected_behavior === "refuse_or_abstain" ? "refuse_or_abstain" : "answer_from_corpus",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const refuse = behavior === "refuse_or_abstain";
  const body = {
    question: isMulti
      ? ([...turns].reverse().find((t) => t.role === "user")?.content.trim() ?? "")
      : question.trim(),
    ground_truth_answer: refuse ? null : answer.trim(),
    expected_sources: refuse
      ? []
      : sources
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
    turns: isMulti
      ? turns.map((t) => ({ role: t.role, content: t.content.trim() })).filter((t) => t.content)
      : null,
    question_type: type.trim() || null,
    expected_behavior: behavior,
  };
  const before = {
    question: item.question,
    ground_truth_answer: item.ground_truth_answer ?? null,
    expected_sources: item.expected_sources.map(sourceName),
    turns: isMulti ? (item.turns ?? []).map((t) => ({ role: t.role, content: t.content })) : null,
    question_type:
      typeof item.metadata?.question_type === "string" ? item.metadata.question_type : null,
    expected_behavior: (item.metadata?.expected_behavior as string) ?? "answer_from_corpus",
  };
  const dirty = JSON.stringify(body) !== JSON.stringify(before);
  const setTurn = (index: number, content: string) =>
    setTurns((prev) => prev.map((turn, i) => (i === index ? { ...turn, content } : turn)));

  async function save() {
    setSaving(true);
    setError(null);
    try {
      onSaved(await updateProfileDatasetItem(profileId, datasetId, item.id, body));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save this row");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="dfb-backdrop" onMouseDown={onClose}>
      <aside
        className="dfb-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="dfb-drawer-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dfb-drawer-head">
          <div style={{ display: "grid", gap: "0.15rem" }}>
            <h3 id="dfb-drawer-title" className="panel-title" style={{ margin: 0 }}>
              Edit row
            </h3>
            <span className="fabric-meta">{KIND_LABEL[kind]}</span>
          </div>
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={onClose}
            aria-label="Close the row editor"
          >
            <IconClose size={13} />
          </button>
        </div>

        <div className="dfb-drawer-body">
          {isMulti ? (
            <div>
              <span className="field-label">Conversation</span>
              <div style={{ display: "grid", gap: "0.5rem" }}>
                {turns.map((turn, index) =>
                  turn.role === "user" ? (
                    <label key={index} style={{ display: "grid", gap: "0.2rem" }}>
                      <span className="fabric-meta">
                        User turn {turns.slice(0, index + 1).filter((t) => t.role === "user").length}
                      </span>
                      <textarea
                        className="input"
                        rows={2}
                        value={turn.content}
                        onChange={(e) => setTurn(index, e.target.value)}
                      />
                    </label>
                  ) : (
                    <div key={index} className="dfb-readonly">
                      <span className="fabric-meta" style={{ display: "block" }}>
                        Assistant turn, kept as written
                      </span>
                      {turn.content}
                    </div>
                  ),
                )}
              </div>
              <p className="field-hint" style={{ marginBottom: 0 }}>
                The row&apos;s question is its last user turn.
              </p>
            </div>
          ) : (
            <div>
              <label className="field-label" htmlFor="dfb-edit-question">
                Question
              </label>
              <textarea
                id="dfb-edit-question"
                className="input"
                rows={2}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                autoFocus
              />
            </div>
          )}

          <div>
            <label className="field-label" htmlFor="dfb-edit-answer">
              Ground-truth answer
            </label>
            <textarea
              id="dfb-edit-answer"
              className="input"
              rows={5}
              value={refuse ? "" : answer}
              disabled={refuse}
              onChange={(e) => setAnswer(e.target.value)}
            />
            <p className="field-hint" style={{ marginBottom: 0 }}>
              An empty answer is refused unless the expected behavior is to abstain.
            </p>
          </div>

          <div>
            <label className="field-label" htmlFor="dfb-edit-sources">
              Expected sources
            </label>
            <input
              id="dfb-edit-sources"
              className="input"
              value={refuse ? "" : sources}
              disabled={refuse}
              placeholder="file-one.pdf, file-two.pdf"
              onChange={(e) => setSources(e.target.value)}
            />
          </div>

          <div className="dfb-two">
            <div>
              <label className="field-label" htmlFor="dfb-edit-type">
                Question type
              </label>
              <input
                id="dfb-edit-type"
                className="input"
                list="dfb-edit-type-list"
                value={type}
                onChange={(e) => setType(e.target.value)}
              />
              <datalist id="dfb-edit-type-list">
                {QUESTION_TYPES[kind].map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
            </div>
            <div>
              <label className="field-label" htmlFor="dfb-edit-behavior">
                Expected behavior
              </label>
              <select
                id="dfb-edit-behavior"
                className="input"
                value={behavior}
                onChange={(e) => setBehavior(e.target.value as Behavior)}
              >
                <option value="answer_from_corpus">Answer from corpus</option>
                <option value="refuse_or_abstain">Refuse or abstain</option>
              </select>
            </div>
          </div>
        </div>

        <div className="dfb-drawer-foot">
          {error && (
            <span role="alert" style={{ flex: 1, color: "var(--danger)", fontSize: "0.8rem" }}>
              {error}
            </span>
          )}
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void save()}
            disabled={!dirty || saving}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </aside>
    </div>
  );
}

export default function DatasetFeedbackPage() {
  const navigate = useNavigate();

  // ── Select view ───────────────────────────────────────────────────────
  const [profiles, setProfiles] = useState<DatasetProfile[]>([]);
  const [profileId, setProfileId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"select" | "creator">("select");
  const [kind, setKind] = useState<DatasetKind>("single_turn");

  // ── Conversation list ─────────────────────────────────────────────────
  const [mode, setMode] = useState<FeedbackMode>("all");
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<FeedbackConversation[]>([]);
  const [total, setTotal] = useState(0);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const requestId = useRef(0);

  // ── Transcript and draft row ──────────────────────────────────────────
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<FeedbackConversationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [graded, setGraded] = useState(1);
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<string[]>([]);
  const [sourceInput, setSourceInput] = useState("");
  const [questionType, setQuestionType] = useState("");
  const [behavior, setBehavior] = useState<Behavior>("answer_from_corpus");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set());

  // ── Dataset tray ──────────────────────────────────────────────────────
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [trayPage, setTrayPage] = useState(0);
  const [editMode, setEditMode] = useState(false);
  const [editing, setEditing] = useState<DatasetPreviewItem | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  const profile = useMemo(() => profiles.find((p) => p.id === profileId) ?? null, [profiles, profileId]);
  // The newest dataset of this kind: the one Offline Evaluation runs.
  const target = profile?.datasets.find((d) => d.kind === kind) ?? null;
  const isMulti = kind === "multi_turn";
  const added = selectedId !== null && (addedIds.has(selectedId) || items.find((i) => i.session_id === selectedId)?.added === true);
  const pipelineLabel = profile?.pipeline_name || profile?.pipeline_slug || "";

  const loadProfiles = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // A profile with no pipeline has no conversations to offer, so it never appears.
      const linked = (await listDatasetProfiles()).filter((p) => p.pipeline_slug);
      setProfiles(linked);
      setProfileId((prev) => (prev && linked.some((p) => p.id === prev) ? prev : linked[0]?.id ?? null));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the dataset profiles");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProfiles();
  }, [loadProfiles]);

  useEffect(() => {
    const timer = setTimeout(() => setQ(qInput.trim()), 300);
    return () => clearTimeout(timer);
  }, [qInput]);

  const fetchPage = useCallback(
    async (offset: number) => {
      if (!profileId) return;
      const id = ++requestId.current;
      setListLoading(true);
      setListError(null);
      try {
        const res = await listFeedbackConversations(profileId, { kind, mode, q, limit: PAGE_SIZE, offset });
        if (id !== requestId.current) return;
        setItems((prev) => (offset === 0 ? res.items : [...prev, ...res.items]));
        setTotal(res.total);
      } catch (err) {
        if (id === requestId.current) {
          setListError(err instanceof Error ? err.message : "Could not load the conversations");
        }
      } finally {
        if (id === requestId.current) setListLoading(false);
      }
    },
    [profileId, kind, mode, q],
  );

  // Reset to the first page whenever profile, kind, mode, text or a refresh changes.
  useEffect(() => {
    if (view !== "creator") return;
    setItems([]);
    setTotal(0);
    void fetchPage(0);
  }, [view, fetchPage, tick]);

  useEffect(() => {
    if (!profileId || !selectedId) {
      setDetail(null);
      return;
    }
    let live = true;
    setDetailLoading(true);
    getFeedbackConversation(profileId, selectedId)
      .then((d) => {
        if (!live) return;
        setDetail(d);
        setGraded(d.turns.length);
      })
      .catch((err) => {
        if (!live) return;
        setDetail(null);
        setNotice({ kind: "error", text: err instanceof Error ? err.message : "Could not open the conversation" });
      })
      .finally(() => live && setDetailLoading(false));
    return () => {
      live = false;
    };
  }, [profileId, selectedId]);

  // The pipeline's own answer and sources are only a starting point for the reviewer.
  useEffect(() => {
    if (!detail) return;
    const turn = detail.turns[(isMulti ? graded : 1) - 1] ?? detail.turns[0];
    setAnswer(turn.answer);
    setSources(turn.sources.map((s) => s.name));
    setSourceInput("");
    setBehavior("answer_from_corpus");
  }, [detail, graded, isMulti]);

  useEffect(() => {
    setTrayPage(0);
    setEditMode(false);
    setEditing(null);
    setSavedMsg(null);
    if (view !== "creator" || !profileId || !target) {
      setPreview(null);
      return;
    }
    let live = true;
    previewProfileDataset(profileId, target.dataset_id)
      .then((p) => live && setPreview(p))
      .catch(() => live && setPreview(null));
    return () => {
      live = false;
    };
  }, [view, profileId, target?.dataset_id, target?.row_count]);

  function openCreator(next: DatasetKind) {
    setKind(next);
    setMode("all");
    setQInput("");
    setQ("");
    setSelectedId(null);
    setDetail(null);
    setNotice(null);
    setAddedIds(new Set());
    setView("creator");
  }

  function addSource() {
    const name = sourceInput.trim();
    if (name && !sources.includes(name)) setSources([...sources, name]);
    setSourceInput("");
  }

  function onSourceKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      addSource();
    }
  }

  const refuse = behavior === "refuse_or_abstain";
  const canAdd = !saving && !added && (refuse || answer.trim() !== "");

  async function onAdd() {
    if (!profile || !detail) return;
    setSaving(true);
    setNotice(null);
    try {
      const res = await appendFeedbackRows(profile.id, kind, [
        {
          session_id: detail.session_id,
          graded_turn: isMulti ? graded : null,
          ground_truth_answer: refuse ? null : answer.trim(),
          expected_sources: refuse ? [] : sources,
          question_type: questionType.trim() || null,
          expected_behavior: behavior,
        },
      ]);
      const skipped = res.skipped[0];
      if (res.added > 0) {
        setAddedIds((prev) => new Set(prev).add(detail.session_id));
        const n = res.dataset.row_count ?? 0;
        setNotice({ kind: "ok", text: `Added. The dataset now has ${n} row${n === 1 ? "" : "s"}.` });
        await loadProfiles();
      } else if (skipped) {
        if (skipped.reason === "already_added") setAddedIds((prev) => new Set(prev).add(detail.session_id));
        setNotice({
          kind: "error",
          text: SKIP_TEXT[skipped.reason] ?? (skipped.detail || "The row could not be added."),
        });
      }
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Could not add the row" });
    } finally {
      setSaving(false);
    }
  }

  const refresh = () => {
    void loadProfiles();
    setTick((n) => n + 1);
  };

  const rows = preview?.items ?? [];
  const trayPageCount = Math.max(1, Math.ceil(rows.length / TRAY_PAGE_SIZE));
  const trayRows = rows.slice(trayPage * TRAY_PAGE_SIZE, trayPage * TRAY_PAGE_SIZE + TRAY_PAGE_SIZE);

  return (
    <>
      <PageHeader
        title="Dataset Feedback"
        description="Turn real test and prod conversations of a pipeline into golden dataset rows."
        breadcrumbs={[
          { label: "Overview", to: "/" },
          { label: "Dataset Feedback", to: "/dataset-feedback" },
        ]}
        actions={
          <button type="button" className="btn btn-secondary" onClick={refresh} disabled={loading} title="Reload profiles and conversations">
            <IconRefresh size={15} />
            Refresh
          </button>
        }
      />

      {error && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: "1rem" }}>
          {error}
        </div>
      )}

      {view === "select" && (
        <div className="fabric-grid">
          <div className="panel">
            <div className="panel-header">
              <h3 className="panel-title">Linked profiles</h3>
              <span className="fabric-meta">{profiles.length} linked</span>
            </div>
            {loading ? (
              <p className="panel-empty muted">Loading…</p>
            ) : profiles.length === 0 ? (
              <div className="panel-empty">
                <IconBucket size={28} className="muted" />
                <p className="muted" style={{ margin: 0 }}>
                  Link a Dataset Fabric profile to a pipeline first.
                </p>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigate("/dataset-fabric")}>
                  Open Dataset Fabric
                  <IconChevronRight size={13} />
                </button>
              </div>
            ) : (
              <div className="fabric-list">
                {profiles.map((p) => {
                  const active = p.id === profileId;
                  const count = (k: DatasetKind) => p.datasets.filter((d) => d.kind === k).length;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      className={`fabric-profile${active ? " fabric-profile--active" : ""}`}
                      aria-current={active ? "true" : undefined}
                      onClick={() => setProfileId(p.id)}
                    >
                      <span className="fabric-avatar" aria-hidden="true">
                        {initials(p.name)}
                      </span>
                      <span style={{ display: "grid", gap: "0.15rem", minWidth: 0, flex: 1 }}>
                        <span className="fabric-name fabric-ellipsis">{p.name}</span>
                        <span style={{ display: "flex", gap: "0.35rem", alignItems: "center", flexWrap: "wrap" }}>
                          <span className="fabric-chip fabric-chip--linked">{p.pipeline_name || p.pipeline_slug}</span>
                          <span className="fabric-meta">
                            {count("single_turn")} single-turn · {count("multi_turn")} multi-turn
                          </span>
                        </span>
                      </span>
                      <IconChevronRight size={14} className="muted" />
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {profile ? (
            <div className="panel" style={{ minWidth: 0 }}>
              <div className="panel-header" style={{ alignItems: "flex-start" }}>
                <div style={{ display: "grid", gap: "0.2rem", minWidth: 0 }}>
                  <h3 className="panel-title" style={{ fontSize: "1rem" }}>
                    {profile.name}
                  </h3>
                  <span className="fabric-meta">Conversations of {pipelineLabel}</span>
                </div>
              </div>
              <div className="fabric-cards">
                {(Object.keys(KIND_LABEL) as DatasetKind[]).map((k) => {
                  const file = profile.datasets.find((d) => d.kind === k);
                  const label = KIND_LABEL[k].toLowerCase();
                  return (
                    <div className="fabric-card" key={k}>
                      <div className="fabric-card-head">
                        <div style={{ display: "grid", gap: "0.1rem", flex: 1, minWidth: 0 }}>
                          <strong style={{ fontSize: "0.875rem" }}>{KIND_LABEL[k]}</strong>
                          <span className="fabric-meta">{KIND_HINT[k]}</span>
                        </div>
                        <button
                          type="button"
                          className={`btn btn-sm ${file ? "btn-secondary" : "btn-primary"}`}
                          style={{ flex: "none" }}
                          onClick={() => openCreator(k)}
                        >
                          {file ? "Add conversations" : `Create ${label} dataset`}
                        </button>
                      </div>
                      <div className="fabric-card-body">
                        {file ? (
                          <div className="fabric-file">
                            <IconFile size={16} className="muted" />
                            <span className="fabric-file-main" style={{ cursor: "default" }}>
                              <span className="fabric-file-name">{file.filename ?? "dataset"}</span>
                              <span className="fabric-meta">
                                {file.row_count ?? "?"} {file.row_count === 1 ? "row" : "rows"} ·{" "}
                                {file.created_at ? formatRelativeTime(file.created_at) : "just now"}
                              </span>
                            </span>
                          </div>
                        ) : (
                          <div className="fabric-empty">No {label} dataset yet.</div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            !loading &&
            profiles.length > 0 && (
              <div className="panel">
                <p className="panel-empty muted">Select a profile.</p>
              </div>
            )
          )}
        </div>
      )}

      {view === "creator" && profile && (
        <>
          <div className="panel" style={{ marginBottom: "1rem" }}>
            <div className="panel-header" style={{ gap: "0.75rem" }}>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setView("select")}>
                <span style={{ display: "inline-flex", transform: "rotate(180deg)" }}>
                  <IconChevronRight size={13} />
                </span>
                Back
              </button>
              <h3 className="panel-title" style={{ fontSize: "1rem", margin: 0, flex: 1, minWidth: 0 }}>
                {profile.name} / {KIND_LABEL[kind]}
              </h3>
              {!target && <span className="fabric-chip">New dataset, created on your first add</span>}
              <span className="fabric-meta">{pipelineLabel}</span>
            </div>
          </div>

          <div className="dfb-grid">
            {/* ── Conversation list ─────────────────────────────────── */}
            <div className="panel" style={{ minWidth: 0 }}>
              <div className="panel-header">
                <h3 className="panel-title">Conversations</h3>
                <span className="fabric-meta">{total}</span>
              </div>
              <div className="dfb-controls">
                <div className="dfb-seg" role="radiogroup" aria-label="Conversation mode">
                  {MODES.map((m) => (
                    <label key={m.value} className="dfb-seg-opt">
                      <input
                        type="radio"
                        name="dfb-mode"
                        value={m.value}
                        checked={mode === m.value}
                        onChange={() => setMode(m.value)}
                      />
                      <span>{m.label}</span>
                    </label>
                  ))}
                </div>
                <div className="dfb-search">
                  <IconSearch size={14} className="muted" />
                  <input
                    className="input"
                    type="search"
                    value={qInput}
                    onChange={(e) => setQInput(e.target.value)}
                    placeholder="Search questions"
                    aria-label="Search questions"
                  />
                </div>
              </div>

              {listError && (
                <div className="alert alert-error" role="alert" style={{ margin: "0 0.75rem 0.75rem" }}>
                  {listError}
                </div>
              )}

              {items.length === 0 ? (
                listLoading ? (
                  <p className="panel-empty muted">Loading conversations…</p>
                ) : (
                  !listError && (
                    <p className="panel-empty muted">
                      No {KIND_LABEL[kind].toLowerCase()} conversations yet for {pipelineLabel}. Chat with the pipeline or
                      call its endpoint. A turn shows up here in about 15 seconds.
                    </p>
                  )
                )
              ) : (
                <div className="dfb-list">
                  {items.map((c) => {
                    const active = c.session_id === selectedId;
                    const isAdded = c.added || addedIds.has(c.session_id);
                    return (
                      <button
                        key={c.session_id}
                        type="button"
                        className={`dfb-item${active ? " dfb-item--active" : ""}`}
                        aria-current={active ? "true" : undefined}
                        onClick={() => {
                          setSelectedId(c.session_id);
                          setNotice(null);
                        }}
                      >
                        <span className="dfb-item-q">{c.first_question || "(no question)"}</span>
                        <span className="dfb-item-meta">
                          <span className="fabric-meta">{formatRelativeTime(c.last_at)}</span>
                          <span className="fabric-chip">{modeLabel(c.trace_modes)}</span>
                          {isMulti && <span className="fabric-meta">{c.turns} turns</span>}
                          {isAdded && (
                            <span className="fabric-chip fabric-chip--linked">
                              <IconCheckCircle size={11} />
                              Added
                            </span>
                          )}
                        </span>
                      </button>
                    );
                  })}
                  {items.length < total && (
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost"
                      style={{ margin: "0.25rem auto" }}
                      disabled={listLoading}
                      onClick={() => void fetchPage(items.length)}
                    >
                      {listLoading ? "Loading…" : "Load more"}
                    </button>
                  )}
                </div>
              )}
            </div>

            {/* ── Transcript, draft row, dataset tray ───────────────── */}
            <div style={{ display: "grid", gap: "1rem", minWidth: 0 }}>
              <div className="panel">
                <div className="panel-header">
                  <h3 className="panel-title">Transcript</h3>
                  {detail && (
                    <span className="fabric-meta" style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                      <span className="fabric-chip">{modeLabel([...new Set(detail.turns.map((t) => t.trace_mode))])}</span>
                      <code>{detail.session_id.slice(0, 8)}</code>
                      {new Date(detail.turns[0].started_at).toLocaleString()}
                    </span>
                  )}
                </div>
                {!selectedId ? (
                  <p className="panel-empty muted">Select a conversation to read it.</p>
                ) : detailLoading || !detail ? (
                  <p className="panel-empty muted">Loading conversation…</p>
                ) : (
                  <div className="dfb-transcript" role={isMulti ? "radiogroup" : undefined} aria-label={isMulti ? "Turn to grade" : undefined}>
                    {detail.turns.map((t) => {
                      const dim = isMulti && t.index > graded;
                      return (
                        <div key={t.index} className={`dfb-turn${dim ? " dfb-turn--dim" : ""}`}>
                          {isMulti && (
                            <div className="dfb-turn-head">
                              <span className="fabric-meta">Turn {t.index}</span>
                              {t.index >= 2 && (
                                <label className="dfb-grade">
                                  <input
                                    type="radio"
                                    name="dfb-graded"
                                    checked={graded === t.index}
                                    onChange={() => setGraded(t.index)}
                                  />
                                  Grade this turn
                                </label>
                              )}
                              {dim && <span className="fabric-chip">Not included</span>}
                            </div>
                          )}
                          <div className="chat-message chat-message--user">
                            <div className="chat-message-header">
                              <span className="chat-role-label">User</span>
                            </div>
                            <div className="chat-bubble chat-bubble--user">{t.question}</div>
                          </div>
                          <div className="chat-message chat-message--assistant">
                            <div className="chat-message-header">
                              <span className="chat-role-label">Pipeline</span>
                            </div>
                            <div className="chat-bubble chat-bubble--assistant">
                              <MarkdownMessage content={t.answer} />
                            </div>
                            {t.sources.length > 0 && (
                              <div className="dfb-chips">
                                {t.sources.map((s) => (
                                  <span key={s.name} className="dfb-src" title={s.name}>
                                    {s.name}
                                    {s.rerank_score !== null && <b>{s.rerank_score.toFixed(2)}</b>}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="panel">
                <div className="panel-header">
                  <h3 className="panel-title">Dataset row</h3>
                  {added && (
                    <span className="fabric-chip fabric-chip--linked">
                      <IconCheckCircle size={11} />
                      Added
                    </span>
                  )}
                </div>
                {!detail ? (
                  <p className="panel-empty muted">Pick a conversation to draft its row.</p>
                ) : (
                  <form
                    className="fabric-create"
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (canAdd) void onAdd();
                    }}
                  >
                    <div>
                      <span className="field-label">{isMulti ? "Conversation" : "Question"}</span>
                      {isMulti ? (
                        <ol className="dfb-readonly dfb-turns">
                          {detail.turns.slice(0, graded).map((t) => (
                            <li key={t.index}>{t.question}</li>
                          ))}
                        </ol>
                      ) : (
                        <div className="dfb-readonly">{detail.turns[0].question}</div>
                      )}
                    </div>

                    <div>
                      <label className="field-label" htmlFor="dfb-answer">
                        Ground-truth answer
                      </label>
                      <textarea
                        id="dfb-answer"
                        className="input"
                        rows={6}
                        value={refuse ? "" : answer}
                        disabled={refuse}
                        onChange={(e) => setAnswer(e.target.value)}
                      />
                      <p className="field-hint" style={{ marginBottom: 0 }}>
                        The pipeline&apos;s answer is only a starting point. Correct it before adding.
                      </p>
                    </div>

                    <div>
                      <label className="field-label" htmlFor="dfb-source">
                        Expected sources
                      </label>
                      {!refuse && sources.length > 0 && (
                        <div className="dfb-chips" style={{ marginBottom: "0.5rem" }}>
                          {sources.map((s) => (
                            <span key={s} className="dfb-src">
                              {s}
                              <button
                                type="button"
                                className="dfb-src-x"
                                aria-label={`Remove ${s}`}
                                onClick={() => setSources(sources.filter((x) => x !== s))}
                              >
                                <IconClose size={11} />
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                      <input
                        id="dfb-source"
                        className="input"
                        value={sourceInput}
                        disabled={refuse}
                        placeholder="File name, then Enter"
                        onChange={(e) => setSourceInput(e.target.value)}
                        onKeyDown={onSourceKey}
                      />
                    </div>

                    <div className="dfb-two">
                      <div>
                        <label className="field-label" htmlFor="dfb-type">
                          Question type
                        </label>
                        <input
                          id="dfb-type"
                          className="input"
                          list="dfb-type-list"
                          value={questionType}
                          onChange={(e) => setQuestionType(e.target.value)}
                        />
                        <datalist id="dfb-type-list">
                          {QUESTION_TYPES[kind].map((t) => (
                            <option key={t} value={t} />
                          ))}
                        </datalist>
                      </div>
                      <div>
                        <label className="field-label" htmlFor="dfb-behavior">
                          Expected behavior
                        </label>
                        <select
                          id="dfb-behavior"
                          className="input"
                          value={behavior}
                          onChange={(e) => setBehavior(e.target.value as Behavior)}
                        >
                          <option value="answer_from_corpus">Answer from corpus</option>
                          <option value="refuse_or_abstain">Refuse or abstain</option>
                        </select>
                      </div>
                    </div>

                    <div className="fabric-create-actions" style={{ alignItems: "center" }}>
                      <span style={{ flex: 1, fontSize: "0.8rem" }}>
                        {notice && (
                          <span
                            role={notice.kind === "ok" ? "status" : "alert"}
                            style={{ color: notice.kind === "ok" ? "var(--success-text)" : "var(--danger)" }}
                          >
                            {notice.text}
                          </span>
                        )}
                      </span>
                      <button type="submit" className="btn btn-primary" disabled={!canAdd}>
                        <IconPlus size={14} />
                        {saving ? "Adding…" : "Add to dataset"}
                      </button>
                    </div>
                  </form>
                )}
              </div>

              <section className="panel" aria-labelledby="dfb-tray-title">
                <div className="panel-header" style={{ alignItems: "flex-start", gap: "0.75rem" }}>
                  <div style={{ display: "grid", gap: "0.2rem", minWidth: 0, flex: 1 }}>
                    <h3 className="panel-title" id="dfb-tray-title">
                      {KIND_LABEL[kind]} dataset - {target?.row_count ?? 0} {target?.row_count === 1 ? "row" : "rows"}
                    </h3>
                    <span className="fabric-meta">
                      {target
                        ? "Each save rewrites this dataset's stored file as JSONL."
                        : "Empty template. Your first added conversation creates this dataset."}
                    </span>
                  </div>
                  {savedMsg && (
                    <span role="status" className="fabric-chip fabric-chip--linked">
                      <IconCheckCircle size={11} />
                      {savedMsg}
                    </span>
                  )}
                  <button
                    type="button"
                    className={`btn btn-sm ${editMode ? "btn-secondary" : "btn-ghost"}`}
                    onClick={() => {
                      setEditMode((value) => !value);
                      setSavedMsg(null);
                    }}
                    disabled={rows.length === 0}
                    aria-pressed={editMode}
                  >
                    <IconEdit size={13} />
                    {editMode ? "Done" : "Edit"}
                  </button>
                </div>
                <div className="fabric-viewer-scroll">
                  <table className="fabric-table">
                    <colgroup>
                      <col style={{ width: "6%" }} />
                      <col style={{ width: editMode ? "24%" : "27%" }} />
                      <col style={{ width: editMode ? "26%" : "29%" }} />
                      <col style={{ width: editMode ? "22%" : "24%" }} />
                      <col style={{ width: editMode ? "12%" : "14%" }} />
                      {editMode && <col style={{ width: "10%" }} />}
                    </colgroup>
                    <thead>
                      <tr>
                        <th scope="col" className="fabric-th-num">
                          #
                        </th>
                        <th scope="col">Question</th>
                        <th scope="col">Ground truth</th>
                        <th scope="col">Sources</th>
                        <th scope="col">Type</th>
                        {editMode && (
                          <th scope="col" className="fabric-th-num">
                            Edit
                          </th>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.length === 0 ? (
                        <tr>
                          <td colSpan={editMode ? 6 : 5}>
                            <div className="fabric-empty">
                              {target
                                ? "This dataset holds no rows."
                                : "Empty template. Your first added conversation creates this dataset."}
                            </div>
                          </td>
                        </tr>
                      ) : (
                        trayRows.map((item, index) => {
                          const rowNumber = trayPage * TRAY_PAGE_SIZE + index + 1;
                          return (
                            <tr key={item.id}>
                              <td className="fabric-td-num">{rowNumber}</td>
                              <td className="fabric-cell">{item.question || "—"}</td>
                              <td className="fabric-cell fabric-cell--muted">
                                {item.ground_truth_answer || "—"}
                              </td>
                              <td className="fabric-cell fabric-cell--muted">
                                {item.expected_sources.length > 0
                                  ? item.expected_sources.map(sourceName).join(", ")
                                  : "—"}
                              </td>
                              <td className="fabric-cell fabric-cell--muted">
                                <span className="fabric-type">
                                  {item.turns
                                    ? `${item.turns.length} turn${item.turns.length === 1 ? "" : "s"}`
                                    : "single"}
                                </span>
                                {typeof item.metadata?.question_type === "string" && (
                                  <span className="fabric-meta">
                                    {String(item.metadata.question_type).replace(/_/g, " ")}
                                  </span>
                                )}
                              </td>
                              {editMode && (
                                <td className="fabric-td-num">
                                  <button
                                    type="button"
                                    className="btn btn-sm btn-ghost"
                                    onClick={() => {
                                      setEditing(item);
                                      setSavedMsg(null);
                                    }}
                                    aria-label={`Edit row ${rowNumber}`}
                                    title="Edit this row"
                                  >
                                    <IconEdit size={13} />
                                  </button>
                                </td>
                              )}
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
                <Pager
                  page={trayPage}
                  pageCount={trayPageCount}
                  from={trayPage * TRAY_PAGE_SIZE + 1}
                  to={trayPage * TRAY_PAGE_SIZE + trayRows.length}
                  total={rows.length}
                  onChange={setTrayPage}
                />
              </section>

              {editing && profileId && target && (
                <RowEditor
                  item={editing}
                  kind={kind}
                  profileId={profileId}
                  datasetId={target.dataset_id}
                  onClose={() => setEditing(null)}
                  onSaved={(updated) => {
                    setPreview((prev) =>
                      prev
                        ? { ...prev, items: prev.items.map((row) => (row.id === updated.id ? updated : row)) }
                        : prev,
                    );
                    setEditing(null);
                    setSavedMsg("Row saved.");
                  }}
                />
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}
