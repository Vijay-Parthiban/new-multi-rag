import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";

import PageHeader from "../components/PageHeader";
import Pager from "../components/Pager";
import RowDrawer, { KIND_WORD } from "../components/RowDrawer";
import StatusBadge from "../components/StatusBadge";
import {
  IconChevronRight,
  IconPlus,
  IconRefresh,
  IconSparkles,
  IconTrash,
} from "../components/Icons";
import {
  KnowledgeProduct,
  SYNTHETIC_EVOLUTIONS,
  SYNTHETIC_RAG_SAFE_EVOLUTIONS,
  SyntheticDatasetKind,
  SyntheticKindConfig,
  SyntheticProfile,
  SyntheticProfileDetail,
  SyntheticVersion,
  SyntheticVersionStatus,
  SyntheticVersionDataset,
  SyntheticVersionItem,
  activateSyntheticVersion,
  addSyntheticDataset,
  createSyntheticProfile,
  createSyntheticVersion,
  deleteSyntheticDataset,
  deleteSyntheticProfile,
  deleteSyntheticVersion,
  getLiteLLMModels,
  getSyntheticProfile,
  getSyntheticVersion,
  listKnowledgeProducts,
  listSyntheticProfiles,
  listSyntheticVersionItems,
  regenerateSyntheticDataset,
  updateSyntheticDataset,
} from "../api";
import { formatRelativeTime } from "../utils/format";

const PAGE_SIZE = 20;

const PHASE_LABEL: Record<string, string> = {
  reading_chunks: "Reading chunks",
  generating_single: "Generating",
  generating_multi: "Generating",
  saving: "Saving",
  done: "Done",
};

const KINDS: SyntheticDatasetKind[] = ["single_turn", "multi_turn"];

/** The form value of one dataset's configuration. Numbers stay strings until submit. */
interface KindDraft {
  rows: string;
  turns: string;
  chunks: string;
  goldens: string;
  filtrationEnabled: boolean;
  threshold: string;
  retries: string;
  evolutions: string[];
  numEvolutions: string;
  task: string;
  scenario: string;
  inputFormat: string;
  expectedOutputFormat: string;
  scenarioContext: string;
  conversationalTask: string;
  participantRoles: string;
}

function newDraft(): KindDraft {
  return {
    rows: "7",
    turns: "2",
    chunks: "4",
    goldens: "2",
    filtrationEnabled: true,
    threshold: "0.5",
    retries: "3",
    evolutions: [...SYNTHETIC_RAG_SAFE_EVOLUTIONS],
    numEvolutions: "1",
    task: "",
    scenario: "",
    inputFormat: "",
    expectedOutputFormat: "",
    scenarioContext: "",
    conversationalTask: "",
    participantRoles: "",
  };
}

function draftFromConfig(config?: Partial<SyntheticKindConfig> | null): KindDraft {
  const base = newDraft();
  if (!config) return base;
  return {
    ...base,
    rows: String(config.rows ?? base.rows),
    turns: String(config.turns ?? base.turns),
    chunks: String(config.chunks_per_context ?? base.chunks),
    goldens: String(config.max_goldens_per_context ?? base.goldens),
    filtrationEnabled: config.filtration?.enabled ?? base.filtrationEnabled,
    threshold: String(config.filtration?.threshold ?? base.threshold),
    retries: String(config.filtration?.max_retries ?? base.retries),
    evolutions: config.evolutions ?? base.evolutions,
    numEvolutions: String(config.num_evolutions ?? base.numEvolutions),
    task: config.styling?.task ?? "",
    scenario: config.styling?.scenario ?? "",
    inputFormat: config.styling?.input_format ?? "",
    expectedOutputFormat: config.styling?.expected_output_format ?? "",
    scenarioContext: config.conversational_styling?.scenario_context ?? "",
    conversationalTask: config.conversational_styling?.conversational_task ?? "",
    participantRoles: config.conversational_styling?.participant_roles ?? "",
  };
}

function optional(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function configFromDraft(draft: KindDraft): SyntheticKindConfig {
  return {
    rows: Number(draft.rows) || 1,
    turns: Number(draft.turns) || 2,
    chunks_per_context: Number(draft.chunks) || 1,
    max_goldens_per_context: Number(draft.goldens) || 1,
    filtration: {
      enabled: draft.filtrationEnabled,
      threshold: Number(draft.threshold) || 0,
      max_retries: Number(draft.retries) || 0,
    },
    evolutions: draft.evolutions,
    num_evolutions: Number(draft.numEvolutions) || 1,
    styling: {
      task: optional(draft.task),
      scenario: optional(draft.scenario),
      input_format: optional(draft.inputFormat),
      expected_output_format: optional(draft.expectedOutputFormat),
    },
    conversational_styling: {
      scenario_context: optional(draft.scenarioContext),
      conversational_task: optional(draft.conversationalTask),
      participant_roles: optional(draft.participantRoles),
    },
  };
}

function progressNumber(progress: Record<string, unknown> | undefined, key: string): number {
  const value = progress?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** One dataset's settings. Shared by the creator's two panes and by the slot editors. */
function KindConfigFields({
  kind,
  draft,
  idPrefix,
  onChange,
}: {
  kind: SyntheticDatasetKind;
  draft: KindDraft;
  idPrefix: string;
  onChange: (next: KindDraft) => void;
}) {
  const set = (patch: Partial<KindDraft>) => onChange({ ...draft, ...patch });
  const multi = kind === "multi_turn";
  return (
    <div className="sd-config">
      <div className="sd-grid">
        <div className="sd-field">
          <label htmlFor={`${idPrefix}-rows`}>Rows to generate</label>
          <input
          className="input"
            id={`${idPrefix}-rows`}
            type="number"
            min={1}
            max={100}
            value={draft.rows}
            onChange={(e) => set({ rows: e.target.value })}
          />
        </div>
        {multi && (
          <div className="sd-field">
            <label htmlFor={`${idPrefix}-turns`}>Turns per conversation</label>
            <input
            className="input"
              id={`${idPrefix}-turns`}
              type="number"
              min={2}
              max={6}
              value={draft.turns}
              onChange={(e) => set({ turns: e.target.value })}
            />
          </div>
        )}
      </div>

      <fieldset className="sd-fieldset">
        <legend>Filtration</legend>
        <label htmlFor={`${idPrefix}-filtration`}>
          <input
            id={`${idPrefix}-filtration`}
            type="checkbox"
            checked={draft.filtrationEnabled}
            onChange={(e) => set({ filtrationEnabled: e.target.checked })}
          />
          Enable filtration
        </label>
        <div className="sd-grid">
          <div className="sd-field">
            <label htmlFor={`${idPrefix}-threshold`}>Threshold</label>
            <input
            className="input"
              id={`${idPrefix}-threshold`}
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={draft.threshold}
              disabled={!draft.filtrationEnabled}
              onChange={(e) => set({ threshold: e.target.value })}
            />
          </div>
          <div className="sd-field">
            <label htmlFor={`${idPrefix}-retries`}>Retries</label>
            <input
            className="input"
              id={`${idPrefix}-retries`}
              type="number"
              min={0}
              max={10}
              value={draft.retries}
              disabled={!draft.filtrationEnabled}
              onChange={(e) => set({ retries: e.target.value })}
            />
          </div>
        </div>
      </fieldset>

      <fieldset className="sd-fieldset">
        <legend>Evolution</legend>
        <div className="sd-checks">
          {SYNTHETIC_EVOLUTIONS.map((name) => (
            <label key={name} htmlFor={`${idPrefix}-evolution-${name}`}>
              <input
                id={`${idPrefix}-evolution-${name}`}
                type="checkbox"
                checked={draft.evolutions.includes(name)}
                onChange={(e) =>
                  set({
                    evolutions: e.target.checked
                      ? [...draft.evolutions, name]
                      : draft.evolutions.filter((item) => item !== name),
                  })
                }
              />
              {name}
            </label>
          ))}
        </div>
        <div className="sd-field">
          <label htmlFor={`${idPrefix}-num-evolutions`}>Evolutions per input</label>
          <input
          className="input"
            id={`${idPrefix}-num-evolutions`}
            type="number"
            min={1}
            max={3}
            value={draft.numEvolutions}
            onChange={(e) => set({ numEvolutions: e.target.value })}
          />
        </div>
      </fieldset>

      <fieldset className="sd-fieldset">
        <legend>Styling</legend>
        <div className="sd-grid">
          {multi ? (
            <>
              <div className="sd-field">
                <label htmlFor={`${idPrefix}-scenario-context`}>Scenario context</label>
                <input
                className="input"
                  id={`${idPrefix}-scenario-context`}
                  value={draft.scenarioContext}
                  onChange={(e) => set({ scenarioContext: e.target.value })}
                />
              </div>
              <div className="sd-field">
                <label htmlFor={`${idPrefix}-conversational-task`}>Conversational task</label>
                <input
                className="input"
                  id={`${idPrefix}-conversational-task`}
                  value={draft.conversationalTask}
                  onChange={(e) => set({ conversationalTask: e.target.value })}
                />
              </div>
              <div className="sd-field">
                <label htmlFor={`${idPrefix}-participant-roles`}>Participant roles</label>
                <input
                className="input"
                  id={`${idPrefix}-participant-roles`}
                  value={draft.participantRoles}
                  onChange={(e) => set({ participantRoles: e.target.value })}
                />
              </div>
            </>
          ) : (
            <>
              <div className="sd-field">
                <label htmlFor={`${idPrefix}-task`}>Task</label>
                <input
                className="input"
                  id={`${idPrefix}-task`}
                  value={draft.task}
                  onChange={(e) => set({ task: e.target.value })}
                />
              </div>
              <div className="sd-field">
                <label htmlFor={`${idPrefix}-scenario`}>Scenario</label>
                <input
                className="input"
                  id={`${idPrefix}-scenario`}
                  value={draft.scenario}
                  onChange={(e) => set({ scenario: e.target.value })}
                />
              </div>
              <div className="sd-field">
                <label htmlFor={`${idPrefix}-input-format`}>Input format</label>
                <input
                className="input"
                  id={`${idPrefix}-input-format`}
                  value={draft.inputFormat}
                  onChange={(e) => set({ inputFormat: e.target.value })}
                />
              </div>
              <div className="sd-field">
                <label htmlFor={`${idPrefix}-output-format`}>Expected output format</label>
                <input
                className="input"
                  id={`${idPrefix}-output-format`}
                  value={draft.expectedOutputFormat}
                  onChange={(e) => set({ expectedOutputFormat: e.target.value })}
                />
              </div>
            </>
          )}
        </div>
      </fieldset>

      <details className="sd-details">
        <summary>Advanced</summary>
        <div className="sd-grid">
          <div className="sd-field">
            <label htmlFor={`${idPrefix}-chunks`}>Chunks per context</label>
            <input
            className="input"
              id={`${idPrefix}-chunks`}
              type="number"
              min={1}
              max={10}
              value={draft.chunks}
              onChange={(e) => set({ chunks: e.target.value })}
            />
          </div>
          <div className="sd-field">
            <label htmlFor={`${idPrefix}-goldens`}>Max goldens per context</label>
            <input
            className="input"
              id={`${idPrefix}-goldens`}
              type="number"
              min={1}
              max={5}
              value={draft.goldens}
              onChange={(e) => set({ goldens: e.target.value })}
            />
          </div>
        </div>
      </details>
    </div>
  );
}

export default function SyntheticDatasetPage() {
  const [profiles, setProfiles] = useState<SyntheticProfile[]>([]);
  const [products, setProducts] = useState<KnowledgeProduct[]>([]);
  // The Knowledge Product the page is looking at. Its synthetic profiles are the only ones
  // shown, and a new profile belongs to it.
  const [productId, setProductId] = useState("");
  const [chatModels, setChatModels] = useState<{ id: string; label: string }[]>([]);
  const [loading, setLoading] = useState(true);

  const [profileId, setProfileId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SyntheticProfileDetail | null>(null);

  const [profileFormOpen, setProfileFormOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");

  const [creatorOpen, setCreatorOpen] = useState(false);
  const [creator, setCreator] = useState({
    versionNo: "",
    description: "",
    model: "",
    type: "single" as "single" | "multi" | "both",
    single: newDraft(),
    multi: newDraft(),
  });

  const [versionId, setVersionId] = useState<string | null>(null);
  const [version, setVersion] = useState<SyntheticVersion | null>(null);
  const versionRef = useRef<HTMLElement | null>(null);
  const [detailRow, setDetailRow] = useState<{
    item: SyntheticVersionItem;
    position: number;
  } | null>(null);

  const [editor, setEditor] = useState<{ kind: SyntheticDatasetKind; mode: "create" | "edit" } | null>(
    null,
  );
  const [editorDraft, setEditorDraft] = useState<KindDraft>(newDraft());

  const [rowsKind, setRowsKind] = useState<SyntheticDatasetKind | null>(null);
  const [rows, setRows] = useState<SyntheticVersionItem[]>([]);
  const [rowCount, setRowCount] = useState(0);
  const [page, setPage] = useState(0);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const profile = detail?.profile ?? profiles.find((p) => p.id === profileId) ?? null;

  const profilesForProduct = useMemo(
    () => profiles.filter((item) => item.knowledge_product_id === productId),
    [profiles, productId],
  );

  const nextVersionNo = useMemo(() => {
    const versions = detail?.versions ?? [];
    return versions.length === 0 ? 1 : Math.max(...versions.map((v) => v.version_no)) + 1;
  }, [detail]);

  const loadProfiles = useCallback(async () => {
    const next = await listSyntheticProfiles();
    setProfiles(next);
    setProfileId((prev) => (prev && next.some((p) => p.id === prev) ? prev : null));
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    setDetail(await getSyntheticProfile(id));
  }, []);

  const refreshVersion = useCallback(async () => {
    if (!versionId) return;
    const next = await getSyntheticVersion(versionId);
    setVersion(next);
  }, [versionId]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [nextProfiles, nextProducts, models] = await Promise.all([
          listSyntheticProfiles(),
          listKnowledgeProducts().catch(() => [] as KnowledgeProduct[]),
          getLiteLLMModels("chat").catch(() => [] as { id: string; label: string }[]),
        ]);
        if (!alive) return;
        setProfiles(nextProfiles);
        setProducts(nextProducts);
        setChatModels(models);
        // Land on the product that already holds presets, else on the first product.
        setProductId(
          (prev) =>
            prev ||
            nextProfiles[0]?.knowledge_product_id ||
            nextProducts[0]?.id ||
            "",
        );
      } catch (exc) {
        if (alive) setError(exc instanceof Error ? exc.message : String(exc));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!profileId) {
      setDetail(null);
      return;
    }
    let alive = true;
    (async () => {
      try {
        const next = await getSyntheticProfile(profileId);
        if (alive) setDetail(next);
      } catch (exc) {
        if (alive) setError(exc instanceof Error ? exc.message : String(exc));
      }
    })();
    return () => {
      alive = false;
    };
  }, [profileId]);

  // The open version refreshes itself while either dataset is queued or running.
  const generating = version?.datasets.some(
    (dataset) => dataset.status === "queued" || dataset.status === "running",
  );
  useEffect(() => {
    if (!versionId || !generating) return;
    let alive = true;
    const timer = setTimeout(async () => {
      try {
        const next = await getSyntheticVersion(versionId);
        if (!alive) return;
        setVersion(next);
        if (profileId) void loadDetail(profileId);
      } catch {
        // A dropped poll is not a failed run.
      }
    }, 1500);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [versionId, version, generating, profileId, loadDetail]);

  useEffect(() => {
    if (!versionId || !rowsKind) return;
    let alive = true;
    (async () => {
      try {
        const next = await listSyntheticVersionItems(versionId, rowsKind, page * PAGE_SIZE, PAGE_SIZE);
        if (!alive) return;
        setRows(next.items);
        setRowCount(next.count);
      } catch (exc) {
        if (alive) setError(exc instanceof Error ? exc.message : String(exc));
      }
    })();
    return () => {
      alive = false;
    };
  }, [versionId, rowsKind, page, version]);

  const selectProfile = (id: string) => {
    const target = profiles.find((item) => item.id === id);
    if (target) setProductId(target.knowledge_product_id);
    setProfileId(id);
    setVersion(null);
    setVersionId(null);
    setRowsKind(null);
    setEditor(null);
    setError(null);
    // A profile with no version opens straight into the creator: that is the only thing
    // left to do there, and it saves a click on every new profile.
    setCreatorOpen((profiles.find((item) => item.id === id)?.version_count ?? 0) === 0);
  };

  const backToProfiles = () => {
    setProfileId(null);
    setDetail(null);
    setVersion(null);
    setVersionId(null);
    setRowsKind(null);
    setEditor(null);
  };

  const onCreateProfile = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await createSyntheticProfile({
        name: newName.trim(),
        description: optional(newDescription),
        knowledge_product_id: productId,
      });
      setNewName("");
      setNewDescription("");
      setProfileFormOpen(false);
      await loadProfiles();
      selectProfile(created.id);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const openCreator = () => {
    setCreator({
      versionNo: "",
      description: "",
      model: chatModels[0]?.id ?? "",
      type: "single",
      single: newDraft(),
      multi: newDraft(),
    });
    setCreatorOpen(true);
  };

  const onCreateVersion = async (event: FormEvent) => {
    event.preventDefault();
    if (!profileId) return;
    setBusy(true);
    setError(null);
    try {
      const kinds: SyntheticDatasetKind[] =
        creator.type === "both"
          ? ["single_turn", "multi_turn"]
          : [creator.type === "single" ? "single_turn" : "multi_turn"];
      const created = await createSyntheticVersion(profileId, {
        version_no: creator.versionNo.trim() ? Number(creator.versionNo) : null,
        description: optional(creator.description),
        model: creator.model,
        kinds,
        single: kinds.includes("single_turn") ? configFromDraft(creator.single) : null,
        multi: kinds.includes("multi_turn") ? configFromDraft(creator.multi) : null,
      });
      setCreatorOpen(false);
      await loadDetail(profileId);
      openVersion(created);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const onActivateVersion = async (row: SyntheticVersion) => {
    if (row.is_active) return;
    setBusy(true);
    setError(null);
    try {
      const next = await activateSyntheticVersion(row.id);
      if (versionId === row.id) setVersion(next);
      if (profileId) await loadDetail(profileId);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!versionId) return;
    const node = versionRef.current;
    if (!node) return;
    const frame = requestAnimationFrame(() => node.scrollIntoView({ block: "nearest" }));
    return () => cancelAnimationFrame(frame);
  }, [versionId]);

  const closeVersion = () => {
    setVersionId(null);
    setVersion(null);
    setRowsKind(null);
    setEditor(null);
    setDetailRow(null);
  };

  const openVersion = (row: SyntheticVersion) => {
    setVersionId(row.id);
    setVersion(row);
    setRowsKind(null);
    setEditor(null);
    setCreatorOpen(false);
    setError(null);
  };

  const onDeleteVersion = async (row: SyntheticVersion) => {
    if (!window.confirm(`Delete version ${row.version_no} and both its datasets?`)) return;
    setBusy(true);
    setError(null);
    try {
      await deleteSyntheticVersion(row.id);
      if (versionId === row.id) {
        setVersionId(null);
        setVersion(null);
        setRowsKind(null);
      }
      if (profileId) await loadDetail(profileId);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const onDeleteProfile = async () => {
    if (!profile) return;
    if (!window.confirm(`Delete the profile "${profile.name}"? Its versions must be deleted first.`))
      return;
    setBusy(true);
    setError(null);
    try {
      await deleteSyntheticProfile(profile.id);
      backToProfiles();
      await loadProfiles();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const openEditor = (kind: SyntheticDatasetKind, mode: "create" | "edit") => {
    const config = version?.config?.[kind === "single_turn" ? "single" : "multi"] as
      | Partial<SyntheticKindConfig>
      | undefined;
    setEditorDraft(draftFromConfig(config));
    setEditor({ kind, mode });
    setError(null);
  };

  const submitEditor = async (regenerate: boolean) => {
    if (!versionId || !editor) return;
    const config = configFromDraft(editorDraft);
    setBusy(true);
    setError(null);
    try {
      const next =
        editor.mode === "create"
          ? await addSyntheticDataset(versionId, editor.kind, config)
          : regenerate
            ? await regenerateSyntheticDataset(versionId, editor.kind, config)
            : await updateSyntheticDataset(versionId, editor.kind, config);
      setVersion(next);
      setEditor(null);
      if (profileId) await loadDetail(profileId);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const onRegenerate = async (kind: SyntheticDatasetKind) => {
    if (!versionId) return;
    if (!window.confirm(`Replace the ${KIND_WORD[kind].toLowerCase()} rows with a new run?`)) return;
    setBusy(true);
    setError(null);
    try {
      const next = await regenerateSyntheticDataset(versionId, kind);
      setVersion(next);
      if (profileId) await loadDetail(profileId);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const onDeleteDataset = async (kind: SyntheticDatasetKind) => {
    if (!versionId) return;
    if (!window.confirm(`Delete the ${KIND_WORD[kind].toLowerCase()} dataset and its rows?`)) return;
    setBusy(true);
    setError(null);
    try {
      await deleteSyntheticDataset(versionId, kind);
      await refreshVersion();
      if (rowsKind === kind) setRowsKind(null);
      if (editor?.kind === kind) setEditor(null);
      if (profileId) await loadDetail(profileId);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const renderSlot = (kind: SyntheticDatasetKind) => {
    const dataset: SyntheticVersionDataset | undefined = version?.datasets.find(
      (item) => item.kind === kind,
    );
    const config = (version?.config?.[kind === "single_turn" ? "single" : "multi"] ??
      {}) as Partial<SyntheticKindConfig>;
    const target = config.rows ?? 0;
    const status = (dataset?.status ?? null) as SyntheticVersionStatus | null;
    const working = status === "queued" || status === "running";
    const progress = dataset?.progress ?? {};
    const contextsTotal = progressNumber(progress, "contexts_total");
    const contextsDone = progressNumber(progress, "contexts_done");
    const editing = editor?.kind === kind;

    return (
      <section className="sd-slot" key={kind}>
        <div className="sd-slot-head">
          <h3 className="sd-pane-title">{KIND_WORD[kind]} dataset</h3>
          {status ? (
            <StatusBadge status={status} />
          ) : (
            <span className="fabric-meta">Not created</span>
          )}
        </div>

        {dataset ? (
          <div className="sd-slot-body">
            <dl className="sd-facts">
              <div>
                <dt>Rows</dt>
                <dd>
                  {dataset.row_count ?? 0}
                  {target ? ` / ${target}` : ""}
                </dd>
              </div>
              <div>
                <dt>Turns</dt>
                <dd>{kind === "multi_turn" ? (config.turns ?? 2) : "—"}</dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>{dataset.created_at ? formatRelativeTime(dataset.created_at) : "—"}</dd>
              </div>
              <div>
                <dt>Fabric</dt>
                <dd>{profile?.fabric_profile_name ?? "—"}</dd>
              </div>
            </dl>

            {working && (
              <div className="sd-progress-inline" aria-live="polite">
                <div className="sd-progress-head">
                  <span className="fabric-meta">
                    {PHASE_LABEL[String(progress.phase ?? "")] ?? "Queued"}
                    {contextsTotal ? ` · ${contextsDone}/${contextsTotal} contexts` : ""}
                  </span>
                </div>
                <div
                  className="sd-bar"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={
                    contextsTotal ? Math.round((contextsDone / contextsTotal) * 100) : 0
                  }
                >
                  <div
                    className="sd-bar-fill"
                    style={{
                      width: `${contextsTotal ? Math.min(100, (contextsDone / contextsTotal) * 100) : 0}%`,
                    }}
                  />
                </div>
              </div>
            )}

            {status === "failed" && (
              <p className="form-error">{String(progress.error ?? version?.error_message ?? "")}</p>
            )}

            <div className="sd-slot-actions">
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => {
                  setRowsKind(kind);
                  setPage(0);
                }}
              >
                View rows
              </button>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => openEditor(kind, "edit")}
                disabled={busy}
              >
                Edit
              </button>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => void onRegenerate(kind)}
                disabled={busy || working}
                title={working ? "Generation is running" : undefined}
              >
                Regenerate
              </button>
              <button
                type="button"
                className="btn btn-sm btn-danger-ghost"
                onClick={() => void onDeleteDataset(kind)}
                disabled={busy}
              >
                <IconTrash size={14} />
                Delete
              </button>
            </div>
          </div>
        ) : (
          <div className="sd-slot-body sd-slot-empty">
            <p className="muted">No {KIND_WORD[kind].toLowerCase()} dataset yet.</p>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => openEditor(kind, "create")}
              disabled={busy || editing}
            >
              <IconPlus size={14} />
              Create {KIND_WORD[kind].toLowerCase()} dataset
            </button>
          </div>
        )}

        {editing && (
          <form
            className="sd-slot-form"
            onSubmit={(event) => {
              event.preventDefault();
              void submitEditor(false);
            }}
          >
            <p className="sd-slot-form-title">
              {editor.mode === "create" ? "New dataset" : "Edit configuration"} ·{" "}
              {KIND_WORD[kind]}
            </p>
            <KindConfigFields
              kind={kind}
              draft={editorDraft}
              idPrefix={`sd-slot-${kind}`}
              onChange={setEditorDraft}
            />
            <div className="sd-form-actions">
              {editor.mode === "create" ? (
                <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>
                  Create and generate
                </button>
              ) : (
                <>
                  <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>
                    Save
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => void submitEditor(true)}
                    disabled={busy}
                  >
                    Save and regenerate
                  </button>
                </>
              )}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setEditor(null)}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </section>
    );
  };

  const creatorKinds: SyntheticDatasetKind[] =
    creator.type === "both"
      ? ["single_turn", "multi_turn"]
      : [creator.type === "single" ? "single_turn" : "multi_turn"];

  return (
    <>
      <PageHeader
        title="Synthetic Datasets"
        description="Pick a Knowledge Product, then keep one active version in each synthetic profile. Each version holds a single-turn dataset and a multi-turn dataset, each with its own settings."
        breadcrumbs={[
          { label: "Overview", to: "/" },
          { label: "Synthetic Datasets", to: "/synthetic-datasets" },
        ]}
        actions={
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => {
              void loadProfiles();
              if (profileId) void loadDetail(profileId);
              if (versionId) void refreshVersion();
            }}
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
              <label htmlFor="sd-product">Knowledge Product</label>
              <select
                className="input"
                id="sd-product"
                value={productId}
                onChange={(e) => {
                  setProductId(e.target.value);
                  setProfileId(null);
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
            <h2 className="sd-section-title">Synthetic profiles</h2>
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
                  <label htmlFor="sd-new-name">Name</label>
                  <input
                    className="input"
                    id="sd-new-name"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    required
                  />
                </div>
                <div className="sd-field">
                  <label htmlFor="sd-new-description">Description</label>
                  <input
                    className="input"
                    id="sd-new-description"
                    value={newDescription}
                    onChange={(e) => setNewDescription(e.target.value)}
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
            <p className="muted">Loading…</p>
          ) : !productId ? (
            <p className="muted">Pick a Knowledge Product to see its synthetic profiles.</p>
          ) : profilesForProduct.length === 0 ? (
            <div className="panel panel-empty">
              <p className="muted" style={{ margin: 0 }}>
                No synthetic profile for this Knowledge Product yet.
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
                        onClick={() => selectProfile(item.id)}
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
                <span className="mono">{profile?.qdrant_collection}</span>
              </p>
            </div>
            <div className="sd-header-actions">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => (creatorOpen ? setCreatorOpen(false) : openCreator())}
                disabled={busy}
              >
                <IconSparkles size={14} />
                Create dataset version
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
                <span className="fabric-meta">Rows generate after creation</span>
              </div>

              <div className="sd-creator-body">
                <div className="sd-grid">
                  <div className="sd-field">
                    <label htmlFor="sd-version-no">Version no</label>
                    <input
                    className="input"
                      id="sd-version-no"
                      type="number"
                      min={1}
                      placeholder={String(nextVersionNo)}
                      value={creator.versionNo}
                      onChange={(e) => setCreator({ ...creator, versionNo: e.target.value })}
                    />
                  </div>
                  <div className="sd-field">
                    <label htmlFor="sd-description">Description</label>
                    <input
                    className="input"
                      id="sd-description"
                      value={creator.description}
                      onChange={(e) => setCreator({ ...creator, description: e.target.value })}
                    />
                  </div>
                  <div className="sd-field">
                    <label htmlFor="sd-model">Chat model</label>
                    <select
                    className="input"
                      id="sd-model"
                      value={creator.model}
                      onChange={(e) => setCreator({ ...creator, model: e.target.value })}
                      required
                    >
                      <option value="">Pick a model</option>
                      {chatModels.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <fieldset className="sd-fieldset">
                  <legend>Dataset type</legend>
                  <div className="sd-radios">
                    {(["single", "multi", "both"] as const).map((type) => (
                      <label key={type} htmlFor={`sd-type-${type}`}>
                        <input
                          id={`sd-type-${type}`}
                          type="radio"
                          name="sd-type"
                          checked={creator.type === type}
                          onChange={() => setCreator({ ...creator, type })}
                        />
                        {type === "single"
                          ? "Single-turn only"
                          : type === "multi"
                            ? "Multi-turn only"
                            : "Both"}
                      </label>
                    ))}
                  </div>
                </fieldset>

                <div className={`sd-panes${creatorKinds.length === 1 ? " sd-panes--single" : ""}`}>
                  {creatorKinds.map((kind) => (
                    <section className="sd-pane" key={kind}>
                      <h4 className="sd-pane-title">{KIND_WORD[kind]} dataset</h4>
                      <KindConfigFields
                        kind={kind}
                        draft={kind === "single_turn" ? creator.single : creator.multi}
                        idPrefix={`sd-create-${kind}`}
                        onChange={(next) =>
                          setCreator(
                            kind === "single_turn"
                              ? { ...creator, single: next }
                              : { ...creator, multi: next },
                          )
                        }
                      />
                    </section>
                  ))}
                </div>

                <div className="sd-form-actions">
                  <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>
                    Create dataset version
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
              <p className="sd-empty muted">No versions yet.</p>
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
                                {KIND_WORD[kind].replace("-turn", "")}
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
                            disabled={busy}
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
                            onClick={() => openVersion(row)}
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
                    onClick={closeVersion}
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
                <StatusBadge status={version.status} />
              </div>

              <div className="sd-version-body">
                <div className="sd-panes sd-panes--divided">
                  {KINDS.map((kind) => renderSlot(kind))}
                </div>
              </div>

              {rowsKind && (
                <div className="sd-rows">
                  <div className="sd-rows-head">
                    <h3 className="panel-title">{KIND_WORD[rowsKind]} rows</h3>
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost"
                      onClick={() => {
                        setRowsKind(null);
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
                                    {(row.expected_sources ?? [])
                                      .map((source) => String(source))
                                      .join(", ") || "—"}
                                  </span>
                                </td>
                                <td>
                                  <span className="sd-cell-clamp">
                                    {Array.isArray(row.metadata?.evolutions)
                                      ? (row.metadata.evolutions as unknown[])
                                          .map((name) => String(name))
                                          .join(", ")
                                      : "—"}
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
            </section>
          )}

          {detailRow && rowsKind && (
            <RowDrawer
              item={detailRow.item}
              position={detailRow.position}
              kind={rowsKind}
              onClose={() => setDetailRow(null)}
            />
          )}
        </>
      )}
    </>
  );
}
