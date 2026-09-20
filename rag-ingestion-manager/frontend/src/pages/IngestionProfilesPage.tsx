import React, { useEffect, useState } from "react";
import {
  createIngestionProfile,
  deleteIngestionProfile,
  getDestinationOptions,
  getLiteLLMModels,
  listIngestionProfiles,
  updateIngestionProfile,
  ChunkStrategy,
  IngestionProfile,
  KnowledgeDestinationOption,
  LiteLLMModelOption,
  LiteLLMModelsResponse,
} from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import { formatChunkStrategy } from "../utils/format";
import DestinationConfigFields from "../components/DestinationConfigFields";
import { IconClose, IconDatabase, IconEdit, IconPlus, IconRefresh, IconTrash } from "../components/Icons";

type DestConfigMap = Record<string, { enabled: boolean; config: Record<string, unknown> }>;

// The seven stored strategies. The hint under the select explains the one that is
// chosen, because the difference is in how a boundary is picked, not in a number.
const CHUNK_STRATEGY_OPTIONS: { value: ChunkStrategy; label: string; hint: string }[] = [
  {
    value: "recursive",
    label: "Paragraph and section, packed to size (default)",
    hint: "Splits on headings and blank lines, then packs the pieces into the size window. The original behaviour.",
  },
  {
    value: "fixed",
    label: "Fixed length",
    hint: "Cuts a hard window every Chunk Size characters. Fast, and it ignores headings and paragraphs.",
  },
  {
    value: "sentence",
    label: "Sentence",
    hint: "Cuts on sentence ends and packs whole sentences into the size window. No sentence is split.",
  },
  {
    value: "section",
    label: "Paragraph and section, one chunk each",
    hint: "One chunk per heading or paragraph, of any length. A block larger than Chunk Size is cut further.",
  },
  {
    value: "layout",
    label: "Document layout (PDF blocks)",
    hint: "Uses the PDF's own layout blocks, so a table region or a heading stays with its body. Other formats behave like the section strategy.",
  },
  {
    value: "context_aware",
    label: "Context aware (topic shifts)",
    hint: "Groups sentences by topic, measured with the Text Embedding Model. One extra embedding call per page.",
  },
  {
    value: "parent_child",
    label: "Parent and child",
    hint: "Stores a large parent block plus small child chunks that name it, about a third of Chunk Size each.",
  },
];

export default function IngestionProfilesPage() {
  const [profiles, setProfiles] = useState<IngestionProfile[]>([]);
  const [destinationOptions, setDestinationOptions] = useState<KnowledgeDestinationOption[]>([]);
  const [litellmModels, setLitellmModels] = useState<LiteLLMModelOption[]>([]);
  const [litellmWarning, setLitellmWarning] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [editingProfile, setEditingProfile] = useState<IngestionProfile | null>(null);
  const [formName, setFormName] = useState<string>("");
  const [formDescription, setFormDescription] = useState<string>("");
  const [formEnabled, setFormEnabled] = useState<boolean>(true);
  const [formChunkSize, setFormChunkSize] = useState<number>(1000);
  const [formChunkOverlap, setFormChunkOverlap] = useState<number>(120);
  const [formChunkStrategy, setFormChunkStrategy] = useState<ChunkStrategy>("recursive");
  const [formModalityMode, setFormModalityMode] = useState<"text" | "text_images">("text");
  const [formEmbeddingModel, setFormEmbeddingModel] = useState<string>("");
  const [formCaptionModel, setFormCaptionModel] = useState<string>("");
  const [formImageMinPixels, setFormImageMinPixels] = useState<number>(10000);
  const [destConfigs, setDestConfigs] = useState<DestConfigMap>({});
  const [saving, setSaving] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [profileToDelete, setProfileToDelete] = useState<IngestionProfile | null>(null);
  const [deleting, setDeleting] = useState<boolean>(false);
  const [pageError, setPageError] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    try {
      const [profs, destOpts] = await Promise.all([listIngestionProfiles(), getDestinationOptions()]);
      setProfiles(profs);
      setDestinationOptions(destOpts);
    } catch (err: unknown) {
      console.error("Failed to load Ingestion Profiles:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const buildInitialDestConfigs = (
    options: KnowledgeDestinationOption[],
    profile?: IngestionProfile | null
  ) => {
    const initialDest: DestConfigMap = {};
    options.forEach((opt) => {
      const existing = profile?.destinations.find((d) => d.destination_type === opt.id);
      initialDest[opt.id] = {
        enabled: existing ? existing.enabled : true,
        config: {
          ...opt.default_config,
          ...(existing?.config || {}),
        },
      };
    });
    return initialDest;
  };

  const loadLiteLLMModels = async (): Promise<LiteLLMModelsResponse> => {
    try {
      const response = await getLiteLLMModels("all");
      setLitellmModels(response.models);
      setLitellmWarning(response.warning || null);
      return response;
    } catch {
      setLitellmModels([]);
      setLitellmWarning("Could not load LiteLLM models. You can still type model names manually.");
      return { source: "fallback", litellm_base_url: "", models: [] };
    }
  };

  const openCreateModal = async () => {
    setEditingProfile(null);
    setFormName("");
    setFormDescription("");
    setFormEnabled(true);
    setFormChunkSize(1000);
    setFormChunkOverlap(120);
    setFormChunkStrategy("recursive");
    setFormModalityMode("text");
    setFormEmbeddingModel("");
    setFormCaptionModel("");
    setFormImageMinPixels(10000);
    setDestConfigs(buildInitialDestConfigs(destinationOptions));
    setErrorMsg(null);
    setIsModalOpen(true);
    // Use what this call returns, not the state variables: state has not
    // re-rendered yet, so it is still empty here. The deployment's configured
    // model wins over the proxy list order, whose first entry may be unusable.
    const response = await loadLiteLLMModels();
    const firstEmbedding = response.models.find((m) => m.kind === "embedding");
    setFormEmbeddingModel((previous) => previous || response.default_embedding_model || firstEmbedding?.id || "");
    setFormCaptionModel((previous) => previous || response.default_caption_model || "");
  };

  const openEditModal = async (profile: IngestionProfile) => {
    setEditingProfile(profile);
    setFormName(profile.name);
    setFormDescription(profile.description || "");
    setFormEnabled(profile.enabled);
    setFormChunkSize(profile.chunk_size);
    setFormChunkOverlap(profile.chunk_overlap);
    setFormChunkStrategy(profile.chunk_strategy || "recursive");
    setFormModalityMode(profile.modality_mode || "text");
    setFormEmbeddingModel(profile.text_embedding_model || "");
    setFormCaptionModel(profile.caption_model || "");
    setFormImageMinPixels(profile.image_min_pixels ?? 10000);
    setDestConfigs(buildInitialDestConfigs(destinationOptions, profile));
    setErrorMsg(null);
    setIsModalOpen(true);
    await loadLiteLLMModels();
  };

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formName.trim()) {
      setErrorMsg("Profile name is required.");
      return;
    }
    if (formChunkOverlap >= formChunkSize) {
      setErrorMsg("Chunk overlap must be smaller than the chunk size.");
      return;
    }
    if (!formEmbeddingModel) {
      setErrorMsg("Select a text embedding model.");
      return;
    }
    if (formModalityMode === "text_images" && !formCaptionModel) {
      setErrorMsg("Select a caption model.");
      return;
    }
    if (!Object.values(destConfigs).some((d) => d.enabled)) {
      setErrorMsg("Enable at least one destination.");
      return;
    }

    setSaving(true);
    setErrorMsg(null);

    const payload = {
      name: formName,
      description: formDescription,
      enabled: formEnabled,
      chunk_size: formChunkSize,
      chunk_overlap: formChunkOverlap,
      chunk_strategy: formChunkStrategy,
      modality_mode: formModalityMode,
      text_embedding_model: formEmbeddingModel,
      caption_model: formModalityMode === "text_images" ? formCaptionModel || null : null,
      image_min_pixels: formImageMinPixels,
      destinations: Object.entries(destConfigs).map(([destination_type, val]) => ({
        destination_type,
        enabled: val.enabled,
        config: val.config,
      })),
    };

    try {
      if (editingProfile) {
        await updateIngestionProfile(editingProfile.id, payload);
      } else {
        await createIngestionProfile(payload);
      }
      setIsModalOpen(false);
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save Ingestion Profile.";
      setErrorMsg(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteProfile = async () => {
    if (!profileToDelete) return;
    setDeleting(true);
    setPageError(null);
    try {
      await deleteIngestionProfile(profileToDelete.id);
      setProfileToDelete(null);
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete Ingestion Profile.";
      setProfileToDelete(null);
      setPageError(msg);
    } finally {
      setDeleting(false);
    }
  };

  const destinationName = (destinationType: string) =>
    destinationOptions.find((o) => o.id === destinationType)?.name || destinationType;

  const enabledDestinationCount = (profile: IngestionProfile) =>
    profile.destinations.filter((d) => d.enabled).length;

  const embeddingModels = litellmModels.filter((m) => m.kind === "embedding");
  const chatModels = litellmModels.filter((m) => m.kind === "chat");

  const totalProfiles = profiles.length;

  return (
    <div className="page-container" style={{ padding: "24px", maxWidth: "1400px", margin: "0 auto" }}>
      {/* Header Banner */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "28px",
          background: "linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%)",
          padding: "24px 32px",
          borderRadius: "16px",
          border: "1px solid rgba(255, 255, 255, 0.08)",
          boxShadow: "0 8px 32px rgba(0, 0, 0, 0.3)",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <div
              style={{
                width: "44px",
                height: "44px",
                borderRadius: "12px",
                background: "linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                boxShadow: "0 4px 14px rgba(139, 92, 246, 0.4)",
              }}
            >
              <IconDatabase style={{ width: "24px", height: "24px", color: "#fff" }} />
            </div>
            <div>
              <h1 style={{ margin: 0, fontSize: "24px", fontWeight: 700, color: "#f8fafc" }}>
                Ingestion Profiles
              </h1>
              <p style={{ margin: "4px 0 0 0", fontSize: "14px", color: "#94a3b8" }}>
                Reusable destination and chunking configuration for Knowledge Products.
              </p>
            </div>
          </div>
        </div>

        <div style={{ display: "flex", gap: "12px" }}>
          <button
            onClick={loadData}
            disabled={loading}
            className="btn btn-secondary"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              padding: "10px 18px",
              borderRadius: "10px",
              fontSize: "14px",
              fontWeight: 600,
            }}
          >
            <IconRefresh style={{ width: "16px", height: "16px" }} />
            Refresh
          </button>
          <button
            onClick={openCreateModal}
            className="btn btn-primary"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              padding: "10px 20px",
              borderRadius: "10px",
              fontSize: "14px",
              fontWeight: 600,
              background: "linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)",
              boxShadow: "0 4px 14px rgba(124, 58, 237, 0.4)",
            }}
          >
            <IconPlus style={{ width: "18px", height: "18px" }} />
            Create Ingestion Profile
          </button>
        </div>
      </div>

      {/* Metric Cards Grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: "20px",
          marginBottom: "32px",
        }}
      >
        <div
          style={{
            background: "rgba(30, 41, 59, 0.5)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "14px",
            padding: "20px",
            backdropFilter: "blur(12px)",
          }}
        >
          <div style={{ fontSize: "13px", fontWeight: 600, color: "#94a3b8", marginBottom: "8px" }}>
            Total Profiles
          </div>
          <div style={{ fontSize: "28px", fontWeight: 800, color: "#f8fafc" }}>{totalProfiles}</div>
          <div style={{ fontSize: "12px", color: "#64748b", marginTop: "4px" }}>
            Reusable Ingestion Configurations
          </div>
        </div>

        <div
          style={{
            background: "rgba(30, 41, 59, 0.5)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "14px",
            padding: "20px",
            backdropFilter: "blur(12px)",
          }}
        >
          <div style={{ fontSize: "13px", fontWeight: 600, color: "#94a3b8", marginBottom: "8px" }}>
            Knowledge Products Using A Profile
          </div>
          <div style={{ fontSize: "28px", fontWeight: 800, color: "#a855f7" }}>
            {profiles.reduce((sum, p) => sum + p.product_count, 0)}
          </div>
          <div style={{ fontSize: "12px", color: "#64748b", marginTop: "4px" }}>
            Copies taken at product creation
          </div>
        </div>

        <div
          style={{
            background: "rgba(30, 41, 59, 0.5)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "14px",
            padding: "20px",
            backdropFilter: "blur(12px)",
          }}
        >
          <div style={{ fontSize: "13px", fontWeight: 600, color: "#94a3b8", marginBottom: "8px" }}>
            Destination Catalogue
          </div>
          <div style={{ fontSize: "28px", fontWeight: 800, color: "#38bdf8" }}>
            {destinationOptions.length}
          </div>
          <div style={{ fontSize: "12px", color: "#64748b", marginTop: "4px" }}>
            Vector, Lexical, Database & Cache
          </div>
        </div>
      </div>

      {/* Profiles Grid */}
      {pageError && (
        <div
          style={{
            padding: "12px 16px",
            borderRadius: "10px",
            background: "rgba(239, 68, 68, 0.15)",
            border: "1px solid rgba(239, 68, 68, 0.3)",
            color: "#f87171",
            fontSize: "13px",
            marginBottom: "20px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "12px",
          }}
        >
          <span>{pageError}</span>
          <button
            onClick={() => setPageError(null)}
            style={{ background: "none", border: "none", color: "#f87171", cursor: "pointer", padding: "2px" }}
            aria-label="Dismiss"
          >
            <IconClose style={{ width: "16px", height: "16px" }} />
          </button>
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: "center", padding: "60px 0", color: "#94a3b8" }}>
          Loading Ingestion Profiles...
        </div>
      ) : profiles.length === 0 ? (
        <div
          style={{
            textAlign: "center",
            padding: "60px 20px",
            background: "rgba(30, 41, 59, 0.3)",
            borderRadius: "16px",
            border: "1px dashed rgba(255, 255, 255, 0.12)",
          }}
        >
          <IconDatabase style={{ width: "48px", height: "48px", color: "#64748b", marginBottom: "16px" }} />
          <h3 style={{ margin: "0 0 8px 0", fontSize: "18px", color: "#f8fafc" }}>
            No Ingestion Profiles
          </h3>
          <p style={{ margin: "0 0 24px 0", fontSize: "14px", color: "#94a3b8" }}>
            Create a profile to save your destination stores and chunking settings once, then reuse it for every
            Knowledge Product.
          </p>
          <button onClick={openCreateModal} className="btn btn-primary">
            <IconPlus style={{ width: "16px", height: "16px", marginRight: "8px" }} />
            Create Ingestion Profile
          </button>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "24px" }}>
          {profiles.map((profile) => (
            <div
              key={profile.id}
              style={{
                background: "rgba(30, 41, 59, 0.6)",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: "16px",
                padding: "24px",
                backdropFilter: "blur(12px)",
                boxShadow: "0 4px 20px rgba(0,0,0,0.2)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  marginBottom: "16px",
                }}
              >
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
                    <h2 style={{ margin: 0, fontSize: "20px", fontWeight: 700, color: "#f8fafc" }}>
                      {profile.name}
                    </h2>
                    <span className="status-badge status-paused">
                      {enabledDestinationCount(profile)} of {profile.destinations.length} destinations
                    </span>
                    <span className="status-badge status-paused">
                      Chunk {profile.chunk_size} / {profile.chunk_overlap}
                    </span>
                    <span className="status-badge status-paused">
                      {formatChunkStrategy(profile.chunk_strategy)}
                    </span>
                    <span className="status-badge status-paused">
                      {profile.modality_mode === "text_images" ? "Text + images" : "Text only"}
                    </span>
                    {profile.modality_mode === "text_images" && profile.caption_model && (
                      <span className="status-badge status-paused">Captions: {profile.caption_model}</span>
                    )}
                    {!profile.enabled && <span className="status-badge status-paused">DISABLED</span>}
                  </div>
                  {profile.description && (
                    <p style={{ margin: "6px 0 0 0", fontSize: "14px", color: "#94a3b8" }}>
                      {profile.description}
                    </p>
                  )}
                </div>

                <div style={{ display: "flex", gap: "8px" }}>
                  <button
                    onClick={() => openEditModal(profile)}
                    className="btn btn-secondary"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "6px",
                      padding: "8px 16px",
                      fontSize: "13px",
                      fontWeight: 600,
                    }}
                  >
                    <IconEdit style={{ width: "15px", height: "15px" }} />
                    Edit
                  </button>
                  <button
                    onClick={() => setProfileToDelete(profile)}
                    className="btn btn-secondary"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "6px",
                      padding: "8px 16px",
                      fontSize: "13px",
                      fontWeight: 600,
                      color: "#f87171",
                    }}
                  >
                    <IconTrash style={{ width: "15px", height: "15px" }} />
                    Delete
                  </button>
                </div>
              </div>

              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginBottom: "14px" }}>
                {profile.destinations.map((dest) => (
                  <span
                    key={dest.destination_type}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "8px",
                      padding: "6px 12px",
                      borderRadius: "999px",
                      background: "rgba(30, 41, 59, 0.8)",
                      border: "1px solid rgba(255, 255, 255, 0.1)",
                      fontSize: "12px",
                      color: "#cbd5e1",
                    }}
                  >
                    {destinationName(dest.destination_type)}
                    <span
                      className={dest.enabled ? "status-badge status-synced" : "status-badge status-paused"}
                      style={{ fontSize: "10px" }}
                    >
                      {dest.enabled ? "ENABLED" : "PAUSED"}
                    </span>
                  </span>
                ))}
              </div>

              <div style={{ fontSize: "12px", color: "#64748b" }}>
                {profile.product_count} Knowledge Product(s) use this profile.
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal for Creating / Editing an Ingestion Profile */}
      {isModalOpen && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(0, 0, 0, 0.75)",
            backdropFilter: "blur(8px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            padding: "20px",
          }}
        >
          <div
            style={{
              background: "#0f172a",
              border: "1px solid rgba(255, 255, 255, 0.12)",
              borderRadius: "20px",
              width: "100%",
              maxWidth: "850px",
              maxHeight: "90vh",
              overflowY: "auto",
              padding: "32px",
              boxShadow: "0 20px 50px rgba(0, 0, 0, 0.5)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "24px",
                paddingBottom: "16px",
                borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
              }}
            >
              <h2 style={{ margin: 0, fontSize: "20px", fontWeight: 700, color: "#f8fafc" }}>
                {editingProfile ? "Edit Ingestion Profile" : "Create Ingestion Profile"}
              </h2>
              <button
                onClick={() => setIsModalOpen(false)}
                style={{
                  background: "none",
                  border: "none",
                  color: "#94a3b8",
                  cursor: "pointer",
                  padding: "4px",
                }}
                aria-label="Close"
              >
                <IconClose style={{ width: "20px", height: "20px" }} />
              </button>
            </div>

            {errorMsg && (
              <div
                style={{
                  padding: "12px 16px",
                  borderRadius: "10px",
                  background: "rgba(239, 68, 68, 0.15)",
                  border: "1px solid rgba(239, 68, 68, 0.3)",
                  color: "#f87171",
                  fontSize: "13px",
                  marginBottom: "20px",
                }}
              >
                {errorMsg}
              </div>
            )}

            {editingProfile && (
              <div
                style={{
                  padding: "12px 16px",
                  borderRadius: "10px",
                  background: "rgba(56, 189, 248, 0.1)",
                  border: "1px solid rgba(56, 189, 248, 0.25)",
                  color: "#7dd3fc",
                  fontSize: "13px",
                  marginBottom: "20px",
                }}
              >
                Saving does not change the {editingProfile.product_count} Knowledge Product(s) already using this
                profile. Use Apply Profile on a product to copy the new values.
              </div>
            )}

            <form onSubmit={handleSaveProfile}>
              {/* General Info */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "16px", marginBottom: "24px" }}>
                <div>
                  <label
                    htmlFor="profile-name"
                    style={{ display: "block", fontSize: "13px", fontWeight: 600, color: "#cbd5e1", marginBottom: "6px" }}
                  >
                    Profile Name *
                  </label>
                  <input
                    id="profile-name"
                    type="text"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="e.g. Resume Fanout — Qdrant + OpenSearch"
                    style={{
                      width: "100%",
                      padding: "10px 14px",
                      borderRadius: "10px",
                      background: "rgba(30, 41, 59, 0.8)",
                      border: "1px solid rgba(255, 255, 255, 0.1)",
                      color: "#f8fafc",
                      fontSize: "14px",
                    }}
                  />
                </div>

                <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={formEnabled}
                    onChange={(e) => setFormEnabled(e.target.checked)}
                  />
                  <span style={{ fontSize: "13px", color: "#cbd5e1" }}>Profile enabled</span>
                </label>

                <div>
                  <label
                    htmlFor="profile-description"
                    style={{ display: "block", fontSize: "13px", fontWeight: 600, color: "#cbd5e1", marginBottom: "6px" }}
                  >
                    Description
                  </label>
                  <textarea
                    id="profile-description"
                    value={formDescription}
                    onChange={(e) => setFormDescription(e.target.value)}
                    placeholder="Destination stores and chunking used by every Knowledge Product that picks this profile..."
                    rows={2}
                    style={{
                      width: "100%",
                      padding: "10px 14px",
                      borderRadius: "10px",
                      background: "rgba(30, 41, 59, 0.8)",
                      border: "1px solid rgba(255, 255, 255, 0.1)",
                      color: "#f8fafc",
                      fontSize: "14px",
                      resize: "none",
                    }}
                  />
                </div>

                {/* Chunking */}
                <div
                  style={{
                    padding: "16px",
                    borderRadius: "12px",
                    background: "rgba(30, 41, 59, 0.5)",
                    border: "1px solid rgba(255, 255, 255, 0.08)",
                  }}
                >
                  <div style={{ fontSize: "13px", fontWeight: 700, color: "#cbd5e1", marginBottom: "4px" }}>
                    Chunking
                  </div>
                  <div style={{ fontSize: "12px", color: "#94a3b8", marginBottom: "12px" }}>
                    The strategy decides where one chunk ends and the next starts. Chunk size and overlap apply to
                    every strategy, and to every destination.
                  </div>

                  <div style={{ marginBottom: "16px" }}>
                    <label
                      htmlFor="chunk-strategy"
                      style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "6px" }}
                    >
                      Chunking Strategy
                    </label>
                    <select
                      id="chunk-strategy"
                      value={formChunkStrategy}
                      onChange={(e) => setFormChunkStrategy(e.target.value as ChunkStrategy)}
                      style={{
                        width: "100%",
                        padding: "10px 14px",
                        borderRadius: "10px",
                        background: "rgba(30, 41, 59, 0.8)",
                        border: "1px solid rgba(255, 255, 255, 0.1)",
                        color: "#f8fafc",
                        fontSize: "14px",
                      }}
                    >
                      {CHUNK_STRATEGY_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <div style={{ fontSize: "11px", color: "#64748b", marginTop: "6px" }}>
                      {CHUNK_STRATEGY_OPTIONS.find((o) => o.value === formChunkStrategy)?.hint}
                    </div>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
                    <div>
                      <label
                        htmlFor="chunk-size"
                        style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "6px" }}
                      >
                        Chunk Size (characters)
                      </label>
                      <input
                        id="chunk-size"
                        type="number"
                        min={100}
                        max={8000}
                        value={formChunkSize}
                        onChange={(e) => setFormChunkSize(Number(e.target.value))}
                        style={{
                          width: "100%",
                          padding: "10px 14px",
                          borderRadius: "10px",
                          background: "rgba(30, 41, 59, 0.8)",
                          border: "1px solid rgba(255, 255, 255, 0.1)",
                          color: "#f8fafc",
                          fontSize: "14px",
                        }}
                      />
                    </div>
                    <div>
                      <label
                        htmlFor="chunk-overlap"
                        style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "6px" }}
                      >
                        Chunk Overlap (characters)
                      </label>
                      <input
                        id="chunk-overlap"
                        type="number"
                        min={0}
                        max={2000}
                        value={formChunkOverlap}
                        onChange={(e) => setFormChunkOverlap(Number(e.target.value))}
                        style={{
                          width: "100%",
                          padding: "10px 14px",
                          borderRadius: "10px",
                          background: "rgba(30, 41, 59, 0.8)",
                          border: "1px solid rgba(255, 255, 255, 0.1)",
                          color: "#f8fafc",
                          fontSize: "14px",
                        }}
                      />
                    </div>
                  </div>
                </div>

                {/* Pipeline Stages */}
                <div
                  style={{
                    padding: "16px",
                    borderRadius: "12px",
                    background: "rgba(30, 41, 59, 0.5)",
                    border: "1px solid rgba(255, 255, 255, 0.08)",
                  }}
                >
                  <div style={{ fontSize: "13px", fontWeight: 700, color: "#cbd5e1", marginBottom: "4px" }}>
                    Pipeline Stages
                  </div>
                  <div style={{ fontSize: "12px", color: "#94a3b8", marginBottom: "12px" }}>
                    How a document is read and embedded before it reaches the destination stores.
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
                    <div>
                      <label
                        htmlFor="modality-mode"
                        style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "6px" }}
                      >
                        Modality
                      </label>
                      <select
                        id="modality-mode"
                        value={formModalityMode}
                        onChange={(e) => setFormModalityMode(e.target.value as "text" | "text_images")}
                        style={{
                          width: "100%",
                          padding: "10px 14px",
                          borderRadius: "10px",
                          background: "rgba(30, 41, 59, 0.8)",
                          border: "1px solid rgba(255, 255, 255, 0.1)",
                          color: "#f8fafc",
                          fontSize: "14px",
                        }}
                      >
                        <option value="text">Text only (selectable text and tables)</option>
                        <option value="text_images">Text with images (vision captions for figures)</option>
                      </select>
                      <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}>
                        Text only ignores images and never calls a vision model.
                      </div>
                    </div>
                    <div>
                      <label
                        htmlFor="text-embedding-model"
                        style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "6px" }}
                      >
                        Text Embedding Model
                      </label>
                      <select
                        id="text-embedding-model"
                        value={formEmbeddingModel}
                        onChange={(e) => setFormEmbeddingModel(e.target.value)}
                        style={{
                          width: "100%",
                          padding: "10px 14px",
                          borderRadius: "10px",
                          background: "rgba(30, 41, 59, 0.8)",
                          border: "1px solid rgba(255, 255, 255, 0.1)",
                          color: "#f8fafc",
                          fontSize: "14px",
                        }}
                      >
                        <option value="">Select a model</option>
                        {embeddingModels.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.id}
                          </option>
                        ))}
                        {formEmbeddingModel && !embeddingModels.some((m) => m.id === formEmbeddingModel) && (
                          <option value={formEmbeddingModel}>{formEmbeddingModel}</option>
                        )}
                      </select>
                      <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}>
                        One model for every store. The vector dimension comes from its output.
                      </div>
                    </div>

                    {formModalityMode === "text_images" && (
                      <>
                        <div>
                          <label
                            htmlFor="caption-model"
                            style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "6px" }}
                          >
                            Caption Model
                          </label>
                          <select
                            id="caption-model"
                            value={formCaptionModel}
                            onChange={(e) => setFormCaptionModel(e.target.value)}
                            style={{
                              width: "100%",
                              padding: "10px 14px",
                              borderRadius: "10px",
                              background: "rgba(30, 41, 59, 0.8)",
                              border: "1px solid rgba(255, 255, 255, 0.1)",
                              color: "#f8fafc",
                              fontSize: "14px",
                            }}
                          >
                            <option value="">Select a model</option>
                            {chatModels.map((m) => (
                              <option key={m.id} value={m.id}>
                                {m.id}
                              </option>
                            ))}
                            {formCaptionModel && !chatModels.some((m) => m.id === formCaptionModel) && (
                              <option value={formCaptionModel}>{formCaptionModel}</option>
                            )}
                          </select>
                          <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}>
                            Vision model that writes one caption per figure. The caption is embedded as text.
                          </div>
                        </div>
                        <div>
                          <label
                            htmlFor="image-min-pixels"
                            style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "6px" }}
                          >
                            Minimum Figure Pixels
                          </label>
                          <input
                            id="image-min-pixels"
                            type="number"
                            min={0}
                            value={formImageMinPixels}
                            onChange={(e) => setFormImageMinPixels(Number(e.target.value))}
                            style={{
                              width: "100%",
                              padding: "10px 14px",
                              borderRadius: "10px",
                              background: "rgba(30, 41, 59, 0.8)",
                              border: "1px solid rgba(255, 255, 255, 0.1)",
                              color: "#f8fafc",
                              fontSize: "14px",
                            }}
                          />
                          <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}>
                            Default 10000. Figures smaller than this are skipped, so a logo or rule
                            does not become a chunk.
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>

              {/* Destination Configurations */}
              <div style={{ marginBottom: "32px" }}>
                <label
                  style={{ display: "block", fontSize: "14px", fontWeight: 700, color: "#cbd5e1", marginBottom: "12px" }}
                >
                  Configure Destination Stores
                </label>
                <div style={{ fontSize: "12px", color: "#94a3b8", marginBottom: "12px" }}>
                  Connections come from the server environment. Vector dimensions are derived from the
                  embedding model.
                </div>
                {litellmWarning && (
                  <div style={{ fontSize: "12px", color: "#fbbf24", marginBottom: "10px" }}>
                    {litellmWarning}
                  </div>
                )}
                {litellmModels.length > 0 && (
                  <div style={{ fontSize: "12px", color: "#94a3b8", marginBottom: "12px" }}>
                    LiteLLM models loaded: {litellmModels.length} available for embedding, chat, and sparse fields.
                  </div>
                )}

                <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                  {destinationOptions.map((opt) => {
                    const current = destConfigs[opt.id] || { enabled: true, config: opt.default_config };
                    return (
                      <div
                        key={opt.id}
                        style={{
                          background: "rgba(30, 41, 59, 0.5)",
                          border: "1px solid rgba(255, 255, 255, 0.08)",
                          borderRadius: "12px",
                          padding: "16px",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            marginBottom: "12px",
                          }}
                        >
                          <div>
                            <span
                              style={{ fontSize: "11px", fontWeight: 700, color: "#38bdf8", textTransform: "uppercase" }}
                            >
                              {opt.category}
                            </span>
                            <h4 style={{ margin: "2px 0 0 0", fontSize: "15px", fontWeight: 700, color: "#f8fafc" }}>
                              {opt.name}
                            </h4>
                          </div>

                          <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer" }}>
                            <span style={{ fontSize: "12px", color: "#94a3b8" }}>Enable Fanout</span>
                            <input
                              type="checkbox"
                              checked={current.enabled}
                              onChange={(e) => {
                                setDestConfigs({
                                  ...destConfigs,
                                  [opt.id]: { ...current, enabled: e.target.checked },
                                });
                              }}
                            />
                          </label>
                        </div>

                        {current.enabled && (
                          <div style={{ marginTop: "12px" }}>
                            <DestinationConfigFields
                              option={opt}
                              config={current.config}
                              litellmModels={litellmModels}
                              onChange={(nextConfig) => {
                                setDestConfigs({
                                  ...destConfigs,
                                  [opt.id]: {
                                    ...current,
                                    config: nextConfig,
                                  },
                                });
                              }}
                            />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
                <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "12px" }}>
                  Store names are assigned per Knowledge Product, so two products can share this profile and stay
                  isolated.
                </div>
              </div>

              {/* Form Footer Actions */}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "12px" }}>
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="btn btn-secondary"
                  style={{ padding: "10px 20px" }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="btn btn-primary"
                  style={{
                    padding: "10px 24px",
                    background: "linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)",
                  }}
                >
                  {saving ? "Saving Profile..." : editingProfile ? "Update Profile" : "Create Ingestion Profile"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={profileToDelete !== null}
        title="Delete Ingestion Profile?"
        message={`Delete '${profileToDelete?.name ?? ""}'? Knowledge Products already created keep their own copy of its destinations.`}
        details={
          profileToDelete
            ? [
                `Destinations: ${profileToDelete.destinations.length}`,
                `Chunk size / overlap: ${profileToDelete.chunk_size} / ${profileToDelete.chunk_overlap}`,
                `Knowledge Products using it: ${profileToDelete.product_count}`,
              ]
            : undefined
        }
        confirmLabel="Delete profile"
        cancelLabel="Keep profile"
        danger
        busy={deleting}
        onConfirm={handleDeleteProfile}
        onCancel={() => setProfileToDelete(null)}
      />
    </div>
  );
}
