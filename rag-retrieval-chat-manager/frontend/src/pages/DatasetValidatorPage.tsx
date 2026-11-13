import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import MarkdownMessage from "../components/MarkdownMessage";
import PageHeader from "../components/PageHeader";
import {
  IconCheckCircle,
  IconChevronRight,
  IconClose,
  IconEdit,
  IconPlus,
  IconRefresh,
  IconSearch,
} from "../components/Icons";
import {
  appendValidatorRows,
  DatasetKind,
  DatasetPreview,
  DatasetPreviewItem,
  getSyntheticProfile,
  getUploadedProfile,
  getValidatorConversation,
  KnowledgeProduct,
  linkValidatorPipeline,
  listKnowledgeProducts,
  listPipelines,
  listSyntheticProfiles,
  listUploadedProfiles,
  listValidatorConversations,
  PipelineRecord,
  previewProfileDataset,
  SyntheticProfile,
  SyntheticProfileDetail,
  updateProfileDatasetItem,
  ValidatorConversation,
  ValidatorConversationDetail,
  ValidatorMode,
} from "../api";
import { QUESTION_TYPES, rowQuestionTypes } from "../questionTypes";
import { formatRelativeTime } from "../utils/format";

const PAGE_SIZE = 25;

type Source = "synthetic" | "manual";

const SOURCE_LABEL: Record<Source, string> = {
  synthetic: "Synthetic profiles",
  manual: "Manual profiles",
};

/**
 * Dataset Validator.
 *
 * Pick a Knowledge Product, then a profile of either author, and the profile opens in a
 * drawer: what it holds, and the pipeline it is linked to. Editing opens the profile's
 * ACTIVE version alone, with the collected turns of that pipeline on the left and every
 * row of the dataset on the right.
 */
const KIND_LABEL: Record<DatasetKind, string> = {
  single_turn: "Single-turn",
  multi_turn: "Multi-turn",
};

const MODES: { value: ValidatorMode; label: string }[] = [
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

const modeLabel = (modes: string[]) =>
  modes.map((m) => (m === "test" ? "Test" : "Prod")).join(" + ");

const sourceName = (s: unknown) =>
  typeof s === "object" && s !== null && "name" in s ? String(s.name) : String(s);

type Turn = { role: string; content: string };

/** The answers a multi-turn row keeps, one per user turn, in `metadata.expected_turns`. */
function expectedAnswers(metadata: Record<string, unknown> | undefined, count: number): string[] {
  const raw = metadata?.expected_turns;
  const stored = Array.isArray(raw)
    ? raw.map((entry) =>
        typeof entry === "string"
          ? entry
          : String((entry as { content?: unknown } | null)?.content ?? ""),
      )
    : [];
  return Array.from({ length: count }, (_, index) => stored[index] ?? "");
}

/** The turns a save sends: each user turn, then its answer. The model splits them again. */
function conversation(turns: Turn[], answers: string[]) {
  return turns
    .flatMap((turn, index) => {
      const user = { role: "user", content: turn.content.trim() };
      const answer = (answers[index] ?? "").trim();
      return answer ? [user, { role: "assistant", content: answer }] : [user];
    })
    .filter((turn) => turn.content);
}

/**
 * A field's value as text. A list or an object is JSON, because a context chunk holds
 * newlines and a line-per-entry format would cut it apart.
 */
function fieldText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value) || typeof value === "object") return JSON.stringify(value, null, 1);
  return String(value);
}

/** The text back in the field's own type, so a number stays a number. */
function fieldValue(stored: unknown, text: string): unknown {
  if (Array.isArray(stored) || (stored !== null && typeof stored === "object")) {
    try {
      return JSON.parse(text);
    } catch {
      return stored;
    }
  }
  if (typeof stored === "number") {
    const parsed = Number(text);
    return Number.isFinite(parsed) ? parsed : stored;
  }
  if (typeof stored === "boolean") return text === "true";
  if (stored === null || stored === undefined) return text.trim() ? text : null;
  return text;
}

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
  const stored = (item.turns ?? []).filter((t) => t.role === "user");
  const [turns, setTurns] = useState<Turn[]>(() =>
    stored.map((t) => ({ role: "user", content: t.content })),
  );
  const [answers, setAnswers] = useState<string[]>(() =>
    expectedAnswers(item.metadata, stored.length),
  );
  const [answer, setAnswer] = useState(item.ground_truth_answer ?? "");
  const [sources, setSources] = useState(item.expected_sources.map(sourceName).join(", "));
  // A synthetic row carries `evolutions`; a manual row or a feedback row carries
  // `question_type`. The picker shows whichever the row has.
  const [type, setType] = useState(() => rowQuestionTypes(item.metadata)[0] ?? "");
  const [behavior, setBehavior] = useState<Behavior>(
    item.metadata?.expected_behavior === "refuse_or_abstain" ? "refuse_or_abstain" : "answer_from_corpus",
  );
  // Every field the row holds, except the ones shown above. The editor shows what the
  // row has, so no empty input appears for a field the row never carried.
  const rowKeys = Object.keys(item.metadata ?? {}).filter(
    (key) =>
      key !== "expected_turns" &&
      key !== "evolutions" &&
      key !== "question_type" &&
      key !== "expected_behavior",
  );
  const [meta, setMeta] = useState<Record<string, string>>(() =>
    Object.fromEntries(rowKeys.map((key) => [key, fieldText(item.metadata[key])])),
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
    turns: isMulti ? conversation(turns, answers) : null,
    question_type: type.trim() || null,
    expected_behavior: behavior,
    metadata: {
      ...Object.fromEntries(
        rowKeys.map((key) => [key, fieldValue(item.metadata[key], meta[key] ?? "")]),
      ),
      // One entry per user turn, so a cleared response stays cleared.
      ...(isMulti
        ? { expected_turns: answers.map((text) => ({ content: text.trim() })) }
        : {}),
    },
  };
  const before = {
    question: item.question,
    ground_truth_answer: item.ground_truth_answer ?? null,
    expected_sources: item.expected_sources.map(sourceName),
    turns: isMulti
      ? conversation(
          stored.map((t) => ({ role: "user" as const, content: t.content })),
          expectedAnswers(item.metadata, stored.length),
        )
      : null,
    question_type: rowQuestionTypes(item.metadata)[0] ?? null,
    expected_behavior: (item.metadata?.expected_behavior as string) ?? "answer_from_corpus",
    metadata: {
      ...Object.fromEntries(rowKeys.map((key) => [key, item.metadata[key]])),
      ...(isMulti
        ? {
            expected_turns: expectedAnswers(item.metadata, stored.length).map((text) => ({
              content: text,
            })),
          }
        : {}),
    },
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
        className="dfb-drawer dv-drawer"
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
                {turns.map((turn, index) => (
                  <div key={index} style={{ display: "grid", gap: "0.35rem" }}>
                    <label style={{ display: "grid", gap: "0.2rem" }}>
                      <span className="fabric-meta">Turn {index + 1} · user</span>
                      <textarea
                        className="input"
                        rows={2}
                        value={turn.content}
                        onChange={(e) => setTurn(index, e.target.value)}
                      />
                    </label>
                    <label style={{ display: "grid", gap: "0.2rem" }}>
                      <span className="fabric-meta">Turn {index + 1} · assistant</span>
                      <textarea
                        className="input"
                        rows={3}
                        value={answers[index] ?? ""}
                        onChange={(e) =>
                          setAnswers((prev) =>
                            prev.map((text, i) => (i === index ? e.target.value : text)),
                          )
                        }
                      />
                    </label>
                  </div>
                ))}
              </div>
              <p className="field-hint" style={{ marginBottom: 0 }}>
                The row&apos;s question is its last user turn. A response is the answer the row
                aims at; the run never replays it.
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
                {QUESTION_TYPES.map((t) => (
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

          {rowKeys.length > 0 && (
            <fieldset className="sd-fieldset">
              <legend>Row fields</legend>
              {rowKeys.map((key) => {
                const stored = item.metadata[key];
                const wide =
                  Array.isArray(stored) || (stored !== null && typeof stored === "object");
                return (
                  <div key={key}>
                    <label className="field-label" htmlFor={`dfb-edit-${key}`}>
                      {key.replace(/_/g, " ")}
                    </label>
                    {wide ? (
                      <textarea
                        id={`dfb-edit-${key}`}
                        className="input"
                        rows={3}
                        value={meta[key] ?? ""}
                        onChange={(e) => setMeta({ ...meta, [key]: e.target.value })}
                      />
                    ) : (
                      <input
                        id={`dfb-edit-${key}`}
                        className="input"
                        value={meta[key] ?? ""}
                        onChange={(e) => setMeta({ ...meta, [key]: e.target.value })}
                      />
                    )}
                  </div>
                );
              })}
            </fieldset>
          )}
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



type ListedProfile = { profile: SyntheticProfile; source: Source };

export default function DatasetValidatorPage() {
  // ── Profile selection ─────────────────────────────────────────────────
  const [products, setProducts] = useState<KnowledgeProduct[]>([]);
  const [pipelines, setPipelines] = useState<PipelineRecord[]>([]);
  const [productId, setProductId] = useState("");
  const [source, setSource] = useState<Source>("synthetic");
  const [synthetic, setSynthetic] = useState<SyntheticProfile[]>([]);
  const [manual, setManual] = useState<SyntheticProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ── Profile drawer ────────────────────────────────────────────────────
  const [drawer, setDrawer] = useState<ListedProfile | null>(null);
  const [drawerDetail, setDrawerDetail] = useState<SyntheticProfileDetail | null>(null);
  const [drawerBusy, setDrawerBusy] = useState(false);
  const [linkSlug, setLinkSlug] = useState("");
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  // ── Editor ────────────────────────────────────────────────────────────
  const [editing, setEditing] = useState<ListedProfile | null>(null);
  const [editingDetail, setEditingDetail] = useState<SyntheticProfileDetail | null>(null);
  const [kind, setKind] = useState<DatasetKind>("single_turn");
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewTick, setPreviewTick] = useState(0);
  const [rowItem, setRowItem] = useState<DatasetPreviewItem | null>(null);

  // ── Conversations of the linked pipeline ──────────────────────────────
  const [mode, setMode] = useState<ValidatorMode>("all");
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<ValidatorConversation[]>([]);
  const [total, setTotal] = useState(0);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const requestId = useRef(0);

  // ── Trace drawer and its draft row ────────────────────────────────────
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ValidatorConversationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [graded, setGraded] = useState(1);
  const [answer, setAnswer] = useState("");
  const [sourcesText, setSourcesText] = useState("");
  const [questionType, setQuestionType] = useState("");
  const [behavior, setBehavior] = useState<Behavior>("answer_from_corpus");
  const [saving, setSaving] = useState(false);
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set());

  const pool = source === "synthetic" ? synthetic : manual;
  const profilesForProduct = useMemo(
    () => pool.filter((item) => item.knowledge_product_id === productId),
    [pool, productId],
  );

  const version = editingDetail?.versions.find((v) => v.is_active) ?? null;
  const dataset = version?.datasets.find((d) => d.kind === kind) ?? null;
  // The dataset carries its own Fabric profile; the profile-level link is the fallback.
  const fabricId = dataset?.profile_id ?? editing?.profile.fabric_profile_id ?? null;
  const pipelineSlug = editing?.profile.pipeline_slug ?? null;
  const isMulti = kind === "multi_turn";
  const refuse = behavior === "refuse_or_abstain";
  const selectedAdded =
    selectedId !== null &&
    (addedIds.has(selectedId) || items.find((i) => i.session_id === selectedId)?.added === true);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextProducts, nextSynthetic, nextManual, nextPipelines] = await Promise.all([
        listKnowledgeProducts(),
        listSyntheticProfiles(),
        listUploadedProfiles(),
        listPipelines(),
      ]);
      setProducts(nextProducts);
      setSynthetic(nextSynthetic);
      setManual(nextManual);
      setPipelines(nextPipelines.filter((p) => p.slug));
      setProductId(
        (prev) =>
          prev ||
          nextSynthetic[0]?.knowledge_product_id ||
          nextManual[0]?.knowledge_product_id ||
          nextProducts[0]?.id ||
          "",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the profiles");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  useEffect(() => {
    const timer = setTimeout(() => setQ(qInput.trim()), 300);
    return () => clearTimeout(timer);
  }, [qInput]);

  async function openDrawer(profile: SyntheticProfile, from: Source) {
    setDrawerBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next =
        from === "synthetic"
          ? await getSyntheticProfile(profile.id)
          : await getUploadedProfile(profile.id);
      setDrawer({ profile: next.profile, source: from });
      setDrawerDetail(next);
      setLinkSlug(next.profile.pipeline_slug ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open the profile");
    } finally {
      setDrawerBusy(false);
    }
  }

  async function saveLink() {
    if (!drawer) return;
    setDrawerBusy(true);
    setError(null);
    try {
      const picked = pipelines.find((p) => p.slug === linkSlug) ?? null;
      const updated = await linkValidatorPipeline(drawer.profile.id, {
        pipeline_slug: picked?.slug ?? null,
        pipeline_name: picked?.name ?? null,
      });
      const patch = (list: SyntheticProfile[]) =>
        list.map((item) => (item.id === updated.id ? { ...item, ...updated } : item));
      setSynthetic(patch);
      setManual(patch);
      setDrawer((prev) => (prev ? { ...prev, profile: { ...prev.profile, ...updated } } : prev));
      setNotice({
        kind: "ok",
        text: picked ? `Linked to ${picked.name}.` : "The pipeline link is cleared.",
      });
    } catch (err) {
      setNotice({
        kind: "error",
        text: err instanceof Error ? err.message : "Could not save the link",
      });
    } finally {
      setDrawerBusy(false);
    }
  }

  function startEditing() {
    if (!drawer || !drawerDetail) return;
    const active = drawerDetail.versions.find((v) => v.is_active);
    if (!active || active.datasets.length === 0) return;
    setEditing({ profile: drawerDetail.profile, source: drawer.source });
    setEditingDetail(drawerDetail);
    setKind(active.datasets[0].kind);
    setDrawer(null);
    setDrawerDetail(null);
    setSelectedId(null);
    setAddedIds(new Set());
    setMode("all");
    setQInput("");
    setQ("");
    setPreview(null);
    setPreviewTick(0);
  }

  function closeEditor() {
    setEditing(null);
    setEditingDetail(null);
    setPreview(null);
    setPreviewError(null);
    setSelectedId(null);
    setDetail(null);
    setAddedIds(new Set());
    void loadAll();
  }

  // The collected conversations, newest first, for the selected kind.
  useEffect(() => {
    if (!editing || !pipelineSlug) {
      setItems([]);
      setTotal(0);
      return;
    }
    const id = ++requestId.current;
    setListLoading(true);
    setListError(null);
    listValidatorConversations(editing.profile.id, { kind, mode, q, limit: PAGE_SIZE, offset: 0 })
      .then((res) => {
        if (id !== requestId.current) return;
        setItems(res.items);
        setTotal(res.total);
      })
      .catch((err) => {
        if (id === requestId.current) {
          setListError(err instanceof Error ? err.message : "Could not load the conversations");
        }
      })
      .finally(() => {
        if (id === requestId.current) setListLoading(false);
      });
  }, [editing, pipelineSlug, kind, mode, q, tick]);

  async function loadMore() {
    if (!editing) return;
    const id = requestId.current;
    try {
      const res = await listValidatorConversations(editing.profile.id, {
        kind,
        mode,
        q,
        limit: PAGE_SIZE,
        offset: items.length,
      });
      if (id !== requestId.current) return;
      setItems((prev) => [...prev, ...res.items]);
      setTotal(res.total);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Could not load more conversations");
    }
  }

  // The dataset rows of the active version, whole.
  useEffect(() => {
    setPreview(null);
    setPreviewError(null);
    if (!editing || !dataset || !fabricId) return;
    let live = true;
    previewProfileDataset(fabricId, dataset.id)
      .then((p) => live && setPreview(p))
      .catch((err) => {
        if (live) setPreviewError(err instanceof Error ? err.message : "Could not load the rows");
      });
    return () => {
      live = false;
    };
  }, [editing, dataset?.id, fabricId, previewTick]);

  // The transcript of the selected conversation, and the draft answer it seeds.
  useEffect(() => {
    if (!editing || !selectedId) {
      setDetail(null);
      return;
    }
    let live = true;
    setDetailLoading(true);
    getValidatorConversation(editing.profile.id, selectedId)
      .then((d) => {
        if (!live) return;
        setDetail(d);
        setGraded(d.turns.length);
      })
      .catch((err) => {
        if (!live) return;
        setDetail(null);
        setNotice({
          kind: "error",
          text: err instanceof Error ? err.message : "Could not open the conversation",
        });
      })
      .finally(() => live && setDetailLoading(false));
    return () => {
      live = false;
    };
  }, [editing, selectedId]);

  useEffect(() => {
    if (!detail) return;
    const turn = detail.turns[(isMulti ? graded : 1) - 1] ?? detail.turns[0];
    setAnswer(turn.answer);
    setSourcesText(turn.sources.map((s) => s.name).join(", "));
    setBehavior("answer_from_corpus");
    setQuestionType("");
  }, [detail, graded, isMulti]);

  function openTrace(id: string) {
    setSelectedId(id);
    setNotice(null);
  }

  function closeTrace() {
    setSelectedId(null);
    setDetail(null);
  }

  async function addFromTrace() {
    if (!editing || !selectedId) return;
    setSaving(true);
    setNotice(null);
    try {
      const res = await appendValidatorRows(editing.profile.id, kind, [
        {
          session_id: selectedId,
          graded_turn: isMulti ? graded : null,
          ground_truth_answer: refuse ? null : answer.trim(),
          expected_sources: refuse
            ? []
            : sourcesText
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
          question_type: questionType || null,
          expected_behavior: behavior,
        },
      ]);
      if (res.added === 0) {
        const reason = res.skipped[0]?.reason ?? "unknown";
        setNotice({
          kind: "error",
          text: SKIP_TEXT[reason] ?? res.skipped[0]?.detail ?? "The row was not added.",
        });
        return;
      }
      setAddedIds((prev) => new Set(prev).add(selectedId));
      setTick((t) => t + 1);
      setPreviewTick((t) => t + 1);
      const fresh =
        editing.source === "synthetic"
          ? await getSyntheticProfile(editing.profile.id)
          : await getUploadedProfile(editing.profile.id);
      setEditingDetail(fresh);
      closeTrace();
      setNotice({ kind: "ok", text: `Added ${res.added} row to v${version?.version_no}.` });
    } catch (err) {
      setNotice({
        kind: "error",
        text: err instanceof Error ? err.message : "Could not add the row",
      });
    } finally {
      setSaving(false);
    }
  }

  const canAdd = !saving && !selectedAdded && (refuse || answer.trim() !== "");

  function onSourceKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") event.preventDefault();
  }

  const metaText = (item: DatasetPreviewItem, key: string) => {
    const value = item.metadata?.[key];
    return value === undefined || value === null || value === "" ? "—" : String(value);
  };

  // ── Render ────────────────────────────────────────────────────────────
  if (editing) {
    const profile = editing.profile;
    const active = version;
    return (
      <div className="page">
        <PageHeader
          title="Dataset Validator"
          description="Validate the active version of a dataset profile against the conversations its pipeline collected."
          breadcrumbs={[{ label: "Overview", to: "/" }, { label: "Dataset Validator" }]}
          actions={
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setPreviewTick((t) => t + 1);
                setTick((t) => t + 1);
              }}
            >
              <IconRefresh size={14} />
              Refresh
            </button>
          }
        />

        <button
          type="button"
          className="btn btn-ghost btn-sm"
          style={{ marginBottom: "0.75rem" }}
          onClick={closeEditor}
        >
          <IconChevronRight size={14} className="sd-back-icon" />
          All profiles
        </button>

        <div className="sd-profile-head">
          <div>
            <h2 className="sd-section-title">{profile.name}</h2>
            <p className="fabric-meta">
              {profile.knowledge_product_name ?? profile.knowledge_product_id} ·{" "}
              {profile.pipeline_name || profile.pipeline_slug || "Yet to be linked"}
              {active ? ` · v${active.version_no} active` : ""}
            </p>
          </div>
          <div className="sd-header-actions">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => void openDrawer(profile, editing.source)}
            >
              <IconEdit size={14} />
              Profile details
            </button>
          </div>
        </div>

        {notice && (
          <p className={notice.kind === "ok" ? "form-note" : "form-error"}>{notice.text}</p>
        )}

        {!active || active.datasets.length === 0 ? (
          <div className="panel panel-empty">
            <p className="muted" style={{ margin: 0 }}>
              This profile has no active version with a dataset. Set a version active in{" "}
              {SOURCE_LABEL[editing.source]} first.
            </p>
          </div>
        ) : (
          <>
            <div className="dv-kinds" role="group" aria-label="Dataset type">
              {active.datasets.map((entry) => (
                <button
                  key={entry.kind}
                  type="button"
                  className={`dv-kind${entry.kind === kind ? " dv-kind--on" : ""}`}
                  aria-pressed={entry.kind === kind}
                  onClick={() => {
                    setKind(entry.kind);
                    setRowItem(null);
                    closeTrace();
                  }}
                >
                  {KIND_LABEL[entry.kind]}
                  <span className="dv-kind-count">{entry.row_count ?? 0}</span>
                </button>
              ))}
            </div>

            <div className="dfb-grid">
              <section className="panel dv-side">
                <div className="panel-header">
                  <h3 className="panel-title">Pipeline traces</h3>
                  <span className="fabric-meta">
                    {pipelineSlug ? `${total} collected` : "Not linked"}
                  </span>
                </div>

                {!pipelineSlug ? (
                  <div className="dv-empty">
                    <p className="muted" style={{ margin: 0 }}>
                      No pipeline is linked to this profile, so there are no conversations to
                      add.
                    </p>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => void openDrawer(profile, editing.source)}
                    >
                      Link a pipeline
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="dfb-controls">
                      <div className="dfb-search">
                        <IconSearch size={14} />
                        <input
                          className="input"
                          value={qInput}
                          onChange={(event) => setQInput(event.target.value)}
                          placeholder="Search a question"
                          aria-label="Search the conversations"
                        />
                      </div>
                      <div className="dfb-seg" role="group" aria-label="Trace mode">
                        {MODES.map((option) => (
                          <label key={option.value} className="dfb-seg-opt">
                            <input
                              type="radio"
                              name="dv-mode"
                              value={option.value}
                              checked={mode === option.value}
                              onChange={() => setMode(option.value)}
                            />
                            <span>{option.label}</span>
                          </label>
                        ))}
                      </div>
                    </div>

                    {listError && <p className="form-error">{listError}</p>}

                    <ul className="dfb-list">
                      {items.map((item) => (
                        <li key={item.session_id}>
                          <button
                            type="button"
                            className={`dfb-item${selectedId === item.session_id ? " dfb-item--active" : ""}`}
                            onClick={() => openTrace(item.session_id)}
                          >
                            <span className="dfb-item-meta">
                              {item.added ? <IconCheckCircle size={13} /> : null}
                              <span className="fabric-meta">
                                {item.turns} {item.turns === 1 ? "turn" : "turns"} ·{" "}
                                {modeLabel(item.trace_modes)} · {formatRelativeTime(item.first_at)}
                              </span>
                            </span>
                            <span className="dfb-item-q">{item.first_question}</span>
                          </button>
                        </li>
                      ))}
                    </ul>

                    {items.length === 0 && !listLoading ? (
                      <p className="muted" style={{ padding: "0 0.75rem" }}>
                        No {KIND_LABEL[kind].toLowerCase()} conversation from this pipeline yet.
                      </p>
                    ) : null}

                    {items.length < total ? (
                      <div style={{ padding: "0 0.75rem 0.75rem" }}>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => void loadMore()}
                          disabled={listLoading}
                        >
                          Load {Math.min(PAGE_SIZE, total - items.length)} more
                        </button>
                      </div>
                    ) : null}
                  </>
                )}
              </section>

              <section className="panel dv-dataset">
                <div className="panel-header">
                  <h3 className="panel-title">{KIND_LABEL[kind]} dataset</h3>
                  <span className="fabric-meta">
                    {preview?.items.length ?? 0} rows · click a row to edit it
                  </span>
                </div>

                {previewError && <p className="form-error">{previewError}</p>}

                {!preview ? (
                  <p className="muted" style={{ padding: "0 0.9rem 0.9rem" }}>
                    {previewError
                      ? ""
                      : fabricId
                        ? "Loading the rows..."
                        : "This dataset is not linked to a Dataset Fabric profile."}
                  </p>
                ) : preview.items.length === 0 ? (
                  <div className="dv-empty">
                    <p className="muted" style={{ margin: 0 }}>
                      This dataset holds no rows. Add one from the traces on the left.
                    </p>
                  </div>
                ) : (
                  <div className="dv-grid-scroll">
                    <table className="fabric-table dv-grid-table">
                      <thead>
                        <tr>
                          <th scope="col" className="dv-col-num">
                            #
                          </th>
                          <th scope="col">Question type</th>
                          <th scope="col">Question</th>
                          <th scope="col">Ground truth</th>
                          <th scope="col">Sources</th>
                          <th scope="col" className="dv-col-num">
                            Turns
                          </th>
                          <th scope="col">Behavior</th>
                          <th scope="col">Keypoints</th>
                          <th scope="col">Difficulty</th>
                          <th scope="col">Notes</th>
                          <th scope="col">Reference context</th>
                        </tr>
                      </thead>
                      <tbody>
                        {preview.items.map((item, index) => (
                          <tr
                            key={item.id}
                            className="sd-row-click"
                            onClick={() => setRowItem(item)}
                          >
                            <td className="dv-col-num">
                              <button
                                type="button"
                                className="sd-row-index"
                                aria-label={`Edit row ${index + 1}`}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setRowItem(item);
                                }}
                              >
                                {index + 1}
                              </button>
                            </td>
                            <td>{rowQuestionTypes(item.metadata).join(", ") || "—"}</td>
                            <td>
                              <span className="sd-cell-clamp" title={item.question}>
                                {item.question}
                              </span>
                            </td>
                            <td>
                              <span
                                className="sd-cell-clamp"
                                title={item.ground_truth_answer ?? ""}
                              >
                                {item.ground_truth_answer ?? "—"}
                              </span>
                            </td>
                            <td>
                              <span className="sd-cell-clamp">
                                {item.expected_sources.map(sourceName).join(", ") || "—"}
                              </span>
                            </td>
                            <td className="dv-col-num">{item.turns?.length ?? 1}</td>
                            <td>
                              {item.metadata?.expected_behavior === "refuse_or_abstain"
                                ? "Abstain"
                                : "Answer"}
                            </td>
                            <td>
                              <span className="sd-cell-clamp">
                                {metaText(item, "keypoints_covered")}
                              </span>
                            </td>
                            <td>{metaText(item, "difficulty")}</td>
                            <td>
                              <span className="sd-cell-clamp">{metaText(item, "notes")}</span>
                            </td>
                            <td>
                              <span className="sd-cell-clamp">
                                {metaText(item, "reference_context")}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </div>
          </>
        )}

        {selectedId && (
          <div className="dfb-backdrop" onMouseDown={closeTrace}>
            <aside
              className="dfb-drawer dv-drawer"
              role="dialog"
              aria-modal="true"
              aria-labelledby="dv-trace-title"
              onMouseDown={(event) => event.stopPropagation()}
            >
              <div className="dfb-drawer-head">
                <div style={{ display: "grid", gap: "0.15rem" }}>
                  <h3 id="dv-trace-title" className="panel-title" style={{ margin: 0 }}>
                    Add from a trace
                  </h3>
                  <span className="fabric-meta">
                    {pipelineSlug} · {KIND_LABEL[kind]}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  onClick={closeTrace}
                  aria-label="Close the trace"
                >
                  <IconClose size={13} />
                </button>
              </div>

              <div className="dfb-drawer-body">
                {detailLoading && <p className="muted">Loading the conversation...</p>}

                {detail && (
                  <>
                    <div className="dfb-transcript dv-transcript">
                      {detail.turns.map((turn) => (
                        <div
                          key={turn.span_id}
                          className={`dfb-turn${isMulti && turn.index !== graded ? " dfb-turn--dim" : ""}`}
                        >
                          <div className="dfb-turn-head">
                            <span>Turn {turn.index}</span>
                            <span className="fabric-meta">
                              {formatRelativeTime(turn.started_at)}
                            </span>
                          </div>
                          <p className="dfb-item-q">{turn.question}</p>
                          <MarkdownMessage
                            content={turn.answer}
                            className="dfb-answer dv-answer-md"
                          />
                          {turn.sources.length > 0 && (
                            <p className="fabric-meta">
                              {turn.sources.map((s) => s.name).join(", ")}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>

                    {isMulti && (
                      <div className="sd-field">
                        <label htmlFor="dv-graded">Graded turn</label>
                        <select
                          className="input"
                          id="dv-graded"
                          value={graded}
                          onChange={(event) => setGraded(Number(event.target.value))}
                        >
                          {detail.turns.slice(1).map((turn) => (
                            <option key={turn.index} value={turn.index}>
                              Turn {turn.index}: {turn.question.slice(0, 60)}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}

                    <div className="sd-field">
                      <label htmlFor="dv-behavior">Expected behaviour</label>
                      <select
                        className="input"
                        id="dv-behavior"
                        value={behavior}
                        onChange={(event) => setBehavior(event.target.value as Behavior)}
                      >
                        <option value="answer_from_corpus">Answer from the corpus</option>
                        <option value="refuse_or_abstain">Refuse or abstain</option>
                      </select>
                    </div>

                    {!refuse && (
                      <>
                        <div className="sd-field">
                          <label htmlFor="dv-answer">Expected answer</label>
                          <textarea
                            className="input"
                            id="dv-answer"
                            rows={4}
                            value={answer}
                            onChange={(event) => setAnswer(event.target.value)}
                          />
                        </div>
                        <div className="sd-field">
                          <label htmlFor="dv-sources">Expected sources</label>
                          <input
                            className="input"
                            id="dv-sources"
                            value={sourcesText}
                            onChange={(event) => setSourcesText(event.target.value)}
                            onKeyDown={onSourceKey}
                            placeholder="resume-1.pdf, resume-3.pdf"
                          />
                        </div>
                        <div className="sd-field">
                          <label htmlFor="dv-type">Question type</label>
                          <input
                            className="input"
                            id="dv-type"
                            list="dv-type-list"
                            placeholder="Not set"
                            value={questionType}
                            onChange={(event) => setQuestionType(event.target.value)}
                          />
                          <datalist id="dv-type-list">
                            {QUESTION_TYPES.map((name) => (
                              <option key={name} value={name} />
                            ))}
                          </datalist>
                        </div>
                      </>
                    )}

                    {selectedAdded && (
                      <p className="form-note">This conversation is already in the dataset.</p>
                    )}
                  </>
                )}
              </div>

              <div className="dfb-drawer-foot">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => void addFromTrace()}
                  disabled={!canAdd}
                >
                  <IconPlus size={14} />
                  {selectedAdded ? "Already added" : "Add to dataset"}
                </button>
                <button type="button" className="btn btn-ghost" onClick={closeTrace}>
                  Cancel
                </button>
              </div>
            </aside>
          </div>
        )}

        {rowItem && preview && dataset && fabricId && (
          <RowEditor
            item={rowItem}
            kind={kind}
            profileId={fabricId}
            datasetId={dataset.id}
            onClose={() => setRowItem(null)}
            onSaved={(saved) => {
              setPreview((prev) =>
                prev
                  ? { ...prev, items: prev.items.map((i) => (i.id === saved.id ? saved : i)) }
                  : prev,
              );
              setRowItem(null);
            }}
          />
        )}
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader
        title="Dataset Validator"
        description="Pick a Knowledge Product, then a synthetic or a manual profile. The profile opens with the pipeline it validates and the version you marked active."
        breadcrumbs={[{ label: "Overview", to: "/" }, { label: "Dataset Validator" }]}
        actions={
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => void loadAll()}
            disabled={loading}
          >
            <IconRefresh size={14} />
            Refresh
          </button>
        }
      />

      {error && <p className="form-error">{error}</p>}

      <section className="dv-select">
        <div className="dv-filters">
          <div className="sd-field">
            <label htmlFor="dv-product">Knowledge Product</label>
            <select
              className="input"
              id="dv-product"
              value={productId}
              onChange={(event) => setProductId(event.target.value)}
            >
              <option value="">Pick a product</option>
              {products.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.name}
                </option>
              ))}
            </select>
          </div>

          <div className="dv-source" role="group" aria-label="Profile author">
            {(Object.keys(SOURCE_LABEL) as Source[]).map((option) => (
              <button
                key={option}
                type="button"
                className={`dv-source-opt${source === option ? " dv-source-opt--on" : ""}`}
                aria-pressed={source === option}
                onClick={() => setSource(option)}
              >
                {SOURCE_LABEL[option]}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <p className="muted">Loading the profiles...</p>
        ) : !productId ? (
          <p className="muted">Pick a Knowledge Product to see its profiles.</p>
        ) : profilesForProduct.length === 0 ? (
          <div className="panel panel-empty">
            <p className="muted" style={{ margin: 0 }}>
              No {SOURCE_LABEL[source].toLowerCase()} for this Knowledge Product yet.
            </p>
          </div>
        ) : (
          <div className="sd-cards">
            {profilesForProduct.map((profile) => (
              <button
                key={profile.id}
                type="button"
                className="sd-card"
                onClick={() => void openDrawer(profile, source)}
                disabled={drawerBusy}
              >
                <span className="sd-card-name">{profile.name}</span>
                <span className="sd-card-kp">{profile.description ?? "No description"}</span>
                <span className="sd-card-kp">
                  {profile.pipeline_name || profile.pipeline_slug ? (
                    <>Pipeline · {profile.pipeline_name || profile.pipeline_slug}</>
                  ) : (
                    <>Pipeline · yet to be linked</>
                  )}
                </span>
                <span className="sd-card-foot">
                  <span className="sd-card-count">
                    {profile.version_count} {profile.version_count === 1 ? "version" : "versions"}
                  </span>
                  <span className="sd-card-open">Open</span>
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      {drawer && drawerDetail && (
        <div className="dfb-backdrop" onMouseDown={() => setDrawer(null)}>
          <aside
            className="dfb-drawer dv-drawer"
            role="dialog"
            aria-modal="true"
            aria-labelledby="dv-drawer-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="dfb-drawer-head">
              <div style={{ display: "grid", gap: "0.15rem" }}>
                <h3 id="dv-drawer-title" className="panel-title" style={{ margin: 0 }}>
                  {drawer.profile.name}
                </h3>
                <span className="fabric-meta">
                  {SOURCE_LABEL[drawer.source]} ·{" "}
                  {drawer.profile.knowledge_product_name ?? drawer.profile.knowledge_product_id}
                </span>
              </div>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => setDrawer(null)}
                aria-label="Close the profile"
              >
                <IconClose size={13} />
              </button>
            </div>

            <div className="dfb-drawer-body">
              <dl className="sd-facts">
                <div>
                  <dt>Versions</dt>
                  <dd>{drawerDetail.versions.length}</dd>
                </div>
                <div>
                  <dt>Fabric profile</dt>
                  <dd>{drawer.profile.fabric_profile_name ?? "—"}</dd>
                </div>
              </dl>

              <div className="dv-contents">
                <h4 className="dv-contents-title">Active version</h4>
                {activeOf(drawerDetail) ? (
                  <>
                    <p className="fabric-meta" style={{ margin: 0 }}>
                      v{activeOf(drawerDetail)!.version_no}
                      {activeOf(drawerDetail)!.description
                        ? ` · ${activeOf(drawerDetail)!.description}`
                        : ""}
                    </p>
                    <div className="dv-chip-row">
                      {activeOf(drawerDetail)!.datasets.length === 0 ? (
                        <span className="fabric-meta">No dataset in this version.</span>
                      ) : (
                        activeOf(drawerDetail)!.datasets.map((entry) => (
                          <span key={entry.kind} className="dv-chip">
                            {KIND_LABEL[entry.kind]}
                            <span className="dv-kind-count">{entry.row_count ?? 0}</span>
                          </span>
                        ))
                      )}
                    </div>
                  </>
                ) : (
                  <p className="muted" style={{ margin: 0 }}>
                    No version is active. Set one active in {SOURCE_LABEL[drawer.source]}.
                  </p>
                )}
              </div>

              <div className="sd-field">
                <label htmlFor="dv-pipeline">RAG pipeline</label>
                <select
                  className="input"
                  id="dv-pipeline"
                  value={linkSlug}
                  onChange={(event) => setLinkSlug(event.target.value)}
                >
                  <option value="">Yet to be linked</option>
                  {pipelines.map((pipeline) => (
                    <option key={pipeline.id} value={pipeline.slug ?? ""}>
                      {pipeline.name}
                      {pipeline.slug ? ` · ${pipeline.slug}` : ""}
                    </option>
                  ))}
                </select>
              </div>

              {notice && (
                <p className={notice.kind === "ok" ? "form-note" : "form-error"}>
                  {notice.text}
                </p>
              )}
            </div>

            <div className="dfb-drawer-foot">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void saveLink()}
                disabled={drawerBusy || linkSlug === (drawer.profile.pipeline_slug ?? "")}
              >
                Save link
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={startEditing}
                disabled={
                  drawerBusy ||
                  !activeOf(drawerDetail) ||
                  (activeOf(drawerDetail)?.datasets.length ?? 0) === 0
                }
                title={
                  (activeOf(drawerDetail)?.datasets.length ?? 0) === 0
                    ? "Set a version with a dataset active first"
                    : undefined
                }
              >
                Edit dataset
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => setDrawer(null)}>
                Cancel
              </button>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

function activeOf(detail: SyntheticProfileDetail | null) {
  return detail?.versions.find((version) => version.is_active) ?? null;
}
