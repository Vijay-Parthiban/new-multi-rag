import { useEffect, useState, useCallback, useMemo, useRef, type KeyboardEvent } from "react";
import {
    GuardrailsConfig,
    GuardOption,
    GuardItemOption,
    listAvailableGuards,
    listGuardrailsConfigs,
    createGuardrailsConfig,
    updateGuardrailsConfig,
    deleteGuardrailsConfig,
} from "../api";

const MODES = [
    { id: "input", label: "Input Only" },
    { id: "output", label: "Output Only" },
    { id: "both", label: "Both" },
] as const;

interface ItemPickerProps {
    label: string;
    selected: string[];
    options: GuardItemOption[];
    allowCustom?: boolean;
    /** Free-text keywords only — same list UI, no option chips or typeahead matches. */
    freeText?: boolean;
    placeholder: string;
    onChange: (next: string[]) => void;
}

function ItemPicker({
    label,
    selected,
    options,
    allowCustom = false,
    freeText = false,
    placeholder,
    onChange,
}: ItemPickerProps) {
    const [adding, setAdding] = useState(false);
    const [query, setQuery] = useState("");
    const [highlight, setHighlight] = useState(0);
    const inputRef = useRef<HTMLInputElement>(null);
    const boxRef = useRef<HTMLDivElement>(null);
    const showMatches = !freeText && options.length > 0;

    const optionById = useMemo(() => {
        const map = new Map<string, GuardItemOption>();
        for (const o of options) map.set(o.id, o);
        return map;
    }, [options]);

    const matches = useMemo(() => {
        if (!showMatches) return [];
        const q = query.trim().toLowerCase();
        return options.filter((o) => {
            if (selected.includes(o.id)) return false;
            if (!q) return true;
            return o.label.toLowerCase().includes(q) || o.id.toLowerCase().includes(q);
        });
    }, [options, selected, query, showMatches]);

    useEffect(() => {
        if (adding) inputRef.current?.focus();
    }, [adding]);

    useEffect(() => {
        setHighlight(0);
    }, [query, adding]);

    useEffect(() => {
        if (!adding) return;
        const onDocClick = (e: MouseEvent) => {
            if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
                setAdding(false);
                setQuery("");
            }
        };
        document.addEventListener("mousedown", onDocClick);
        return () => document.removeEventListener("mousedown", onDocClick);
    }, [adding]);

    const addItem = (id: string) => {
        let value = id.trim();
        if (!value) return;
        if (freeText) value = value.toLowerCase();
        const exists = selected.some((s) => s.toLowerCase() === value.toLowerCase());
        if (exists) return;
        onChange([...selected, value]);
        setQuery("");
        setHighlight(0);
        inputRef.current?.focus();
    };

    const removeItem = (id: string) => {
        onChange(selected.filter((s) => s !== id));
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
        if (showMatches && e.key === "ArrowDown") {
            e.preventDefault();
            setHighlight((h) => Math.min(h + 1, Math.max(0, matches.length - 1)));
        } else if (showMatches && e.key === "ArrowUp") {
            e.preventDefault();
            setHighlight((h) => Math.max(h - 1, 0));
        } else if (e.key === "Enter") {
            e.preventDefault();
            if (showMatches && matches[highlight]) {
                addItem(matches[highlight].id);
            } else if ((allowCustom || freeText) && query.trim()) {
                addItem(query);
            }
        } else if (e.key === "Escape") {
            setAdding(false);
            setQuery("");
        }
    };

    const remaining = options.filter((o) => !selected.includes(o.id));
    const quickPicks = showMatches ? remaining.slice(0, 8) : [];

    return (
        <div className="gr-item-picker">
            <div className="gr-item-picker-label">{label}</div>

            {selected.length > 0 && (
                <div className="gr-selected-tags">
                    {selected.map((id) => (
                        <span key={id} className="gr-selected-tag">
                            {optionById.get(id)?.label || id}
                            <button
                                type="button"
                                className="gr-tag-remove"
                                onClick={() => removeItem(id)}
                                aria-label={`Remove ${id}`}
                            >
                                ×
                            </button>
                        </span>
                    ))}
                </div>
            )}

            {quickPicks.length > 0 && !adding && (
                <div className="gr-quick-picks">
                    {quickPicks.map((o) => (
                        <button
                            key={o.id}
                            type="button"
                            className="gr-quick-pick"
                            onClick={() => addItem(o.id)}
                        >
                            + {o.label}
                        </button>
                    ))}
                </div>
            )}

            <div className="gr-add-row" ref={boxRef}>
                {!adding ? (
                    <button
                        type="button"
                        className="btn btn-sm gr-add-items-btn"
                        onClick={() => setAdding(true)}
                        disabled={!freeText && remaining.length === 0 && !allowCustom}
                    >
                        {freeText || remaining.length > 0 || allowCustom ? "+ Add items" : "All items added"}
                    </button>
                ) : (
                    <div className="gr-combobox">
                        <input
                            ref={inputRef}
                            className="gr-input gr-combobox-input"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder={placeholder}
                        />
                        {showMatches && matches.length > 0 && (
                            <ul className="gr-combobox-list" role="listbox">
                                {matches.map((o, i) => (
                                    <li
                                        key={o.id}
                                        role="option"
                                        aria-selected={i === highlight}
                                        className={`gr-combobox-option ${i === highlight ? "highlighted" : ""}`}
                                        onMouseEnter={() => setHighlight(i)}
                                        onMouseDown={(e) => {
                                            e.preventDefault();
                                            addItem(o.id);
                                        }}
                                    >
                                        {o.label}
                                        {o.label !== o.id && <span className="gr-option-id">{o.id}</span>}
                                    </li>
                                ))}
                            </ul>
                        )}
                        {showMatches && matches.length === 0 && (
                            <div className="gr-combobox-empty">
                                {query.trim() ? "No matching items" : "Type to filter available items"}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}

export default function GuardrailsConfigPage() {
    const [configs, setConfigs] = useState<GuardrailsConfig[]>([]);
    const [guards, setGuards] = useState<GuardOption[]>([]);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);

    const [formName, setFormName] = useState("");
    const [formDescription, setFormDescription] = useState("");
    const [formGuards, setFormGuards] = useState<string[]>([]);
    const [formBannedWords, setFormBannedWords] = useState<string[]>([]);
    const [formPiiEntities, setFormPiiEntities] = useState<string[]>([]);
    const [formMode, setFormMode] = useState("both");
    const [editingId, setEditingId] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const [guardsRes, configsRes] = await Promise.all([
                listAvailableGuards(),
                listGuardrailsConfigs(),
            ]);
            setGuards(guardsRes);
            setConfigs(configsRes.items);
        } catch (e) {
            console.error("Failed to load guardrails", e);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const resetForm = () => {
        setFormName("");
        setFormDescription("");
        setFormGuards([]);
        setFormBannedWords([]);
        setFormPiiEntities([]);
        setFormMode("both");
        setEditingId(null);
        setShowForm(false);
        setFormError(null);
    };

    const toggleGuard = (id: string) => {
        setFormGuards((prev) =>
            prev.includes(id) ? prev.filter((g) => g !== id) : [...prev, id]
        );
        setFormError(null);
    };

    const openEdit = (c: GuardrailsConfig) => {
        setFormName(c.name);
        setFormDescription(c.description || "");
        setFormGuards([...c.guards]);
        setFormBannedWords([...(c.settings?.banned_words || [])].map((w) => w.toLowerCase()));
        setFormPiiEntities([...(c.settings?.pii_entities || [])]);
        setFormMode(c.mode);
        setEditingId(c.id);
        setShowForm(true);
        setFormError(null);
    };

    const canSave = useMemo(() => {
        if (!formName.trim() || formGuards.length === 0) return false;
        if (formGuards.includes("ban_list") && formBannedWords.length === 0) return false;
        if (formGuards.includes("pii_check") && formPiiEntities.length === 0) return false;
        return true;
    }, [formName, formGuards, formBannedWords, formPiiEntities]);

    const handleSave = async () => {
        if (!canSave) {
            if (formGuards.includes("ban_list") && formBannedWords.length === 0) {
                setFormError("Add at least one keyword for Ban List.");
            } else if (formGuards.includes("pii_check") && formPiiEntities.length === 0) {
                setFormError("Select at least one PII type for PII Detection.");
            }
            return;
        }
        setSaving(true);
        setFormError(null);
        const settings = {
            banned_words: formGuards.includes("ban_list") ? formBannedWords : [],
            pii_entities: formGuards.includes("pii_check") ? formPiiEntities : [],
        };
        try {
            if (editingId) {
                await updateGuardrailsConfig(editingId, {
                    name: formName.trim(),
                    description: formDescription.trim() || undefined,
                    guards: formGuards,
                    mode: formMode,
                    settings,
                });
            } else {
                await createGuardrailsConfig({
                    name: formName.trim(),
                    description: formDescription.trim() || undefined,
                    guards: formGuards,
                    mode: formMode,
                    settings,
                });
            }
            resetForm();
            await load();
        } catch (e) {
            console.error("Save failed", e);
            setFormError(e instanceof Error ? e.message : "Save failed");
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async (id: string) => {
        if (!confirm("Delete this guardrails config?")) return;
        try {
            await deleteGuardrailsConfig(id);
            await load();
        } catch (e) {
            console.error("Delete failed", e);
        }
    };

    const handleToggleActive = async (c: GuardrailsConfig) => {
        try {
            await updateGuardrailsConfig(c.id, { is_active: !c.is_active });
            await load();
        } catch (e) {
            console.error("Toggle failed", e);
        }
    };

    const guardMeta = (id: string) => guards.find((g) => g.id === id);
    const guardLabel = (id: string) => guardMeta(id)?.label || id;
    const piiLabel = (id: string) =>
        guards.find((g) => g.id === "pii_check")?.options?.find((o) => o.id === id)?.label || id;

    return (
        <div className="page-container guardrails-page">
            <div className="page-header">
                <h1>⛨ Guard Configuration</h1>
                <button
                    className="btn btn-primary"
                    onClick={() => { resetForm(); setShowForm(true); }}
                >
                    + New Config
                </button>
            </div>

            {showForm && (
                <div className="gr-card gr-form-card">
                    <h3>{editingId ? "Edit Config" : "Create Config"}</h3>

                    <label className="gr-label">Name</label>
                    <input
                        className="gr-input"
                        value={formName}
                        onChange={(e) => setFormName(e.target.value)}
                        placeholder="e.g. Production Safety"
                    />

                    <label className="gr-label">Description (optional)</label>
                    <input
                        className="gr-input"
                        value={formDescription}
                        onChange={(e) => setFormDescription(e.target.value)}
                        placeholder="Brief description..."
                    />

                    <label className="gr-label">Guards</label>
                    <div className="gr-guard-options">
                        {guards.map((g) => {
                            const selected = formGuards.includes(g.id);
                            return (
                                <div key={g.id} className={`gr-guard-block ${selected ? "selected" : ""}`}>
                                    <label className={`gr-guard-chip ${selected ? "selected" : ""}`}>
                                        <input
                                            type="checkbox"
                                            checked={selected}
                                            onChange={() => toggleGuard(g.id)}
                                        />
                                        <span className="gr-chip-label">{g.label}</span>
                                        <span className="gr-chip-desc">{g.description}</span>
                                    </label>
                                    {selected && g.id === "ban_list" && (
                                        <ItemPicker
                                            label={g.items_label || "Keywords"}
                                            selected={formBannedWords}
                                            options={[]}
                                            freeText
                                            placeholder="Type a keyword and press Enter…"
                                            onChange={setFormBannedWords}
                                        />
                                    )}
                                    {selected && g.id === "pii_check" && (
                                        <ItemPicker
                                            label={g.items_label || "PII types"}
                                            selected={formPiiEntities}
                                            options={g.options || []}
                                            placeholder="Type to match a PII type…"
                                            onChange={setFormPiiEntities}
                                        />
                                    )}
                                </div>
                            );
                        })}
                    </div>

                    <label className="gr-label">Mode</label>
                    <div className="gr-mode-radios">
                        {MODES.map((m) => (
                            <label key={m.id} className={`gr-mode-radio ${formMode === m.id ? "selected" : ""}`}>
                                <input
                                    type="radio"
                                    name="gr-mode"
                                    value={m.id}
                                    checked={formMode === m.id}
                                    onChange={() => setFormMode(m.id)}
                                />
                                {m.label}
                            </label>
                        ))}
                    </div>

                    {formError && <p className="gr-form-error">{formError}</p>}

                    <div className="gr-form-actions">
                        <button className="btn btn-secondary" onClick={resetForm}>Cancel</button>
                        <button
                            className="btn btn-primary"
                            onClick={handleSave}
                            disabled={saving || !canSave}
                        >
                            {saving ? "Saving..." : editingId ? "Update" : "Create"}
                        </button>
                    </div>
                </div>
            )}

            {loading ? (
                <p className="gr-loading">Loading configs...</p>
            ) : configs.length === 0 ? (
                <div className="gr-empty">
                    <p>No guardrails configurations yet.</p>
                    <p>Click "+ New Config" to create one.</p>
                </div>
            ) : (
                <div className="gr-config-grid">
                    {configs.map((c) => (
                        <div key={c.id} className={`gr-config-card ${!c.is_active ? "inactive" : ""}`}>
                            <div className="gr-config-header">
                                <h3>{c.name}</h3>
                                <span className={`gr-badge gr-badge-${c.is_active ? "active" : "inactive"}`}>
                                    {c.is_active ? "Active" : "Inactive"}
                                </span>
                            </div>
                            {c.description && <p className="gr-config-desc">{c.description}</p>}
                            <div className="gr-config-detail">
                                <span className="gr-detail-label">Mode:</span>
                                <span className="gr-mode-badge">{c.mode}</span>
                            </div>
                            <div className="gr-config-detail">
                                <span className="gr-detail-label">Guards:</span>
                                <div className="gr-guard-tags">
                                    {c.guards.map((g) => (
                                        <span key={g} className="gr-guard-tag">{guardLabel(g)}</span>
                                    ))}
                                </div>
                            </div>
                            {c.guards.includes("ban_list") && (c.settings?.banned_words?.length ?? 0) > 0 && (
                                <div className="gr-config-detail">
                                    <span className="gr-detail-label">Keywords:</span>
                                    <div className="gr-guard-tags">
                                        {c.settings.banned_words.map((w) => (
                                            <span key={w} className="gr-item-tag">{w}</span>
                                        ))}
                                    </div>
                                </div>
                            )}
                            {c.guards.includes("pii_check") && (c.settings?.pii_entities?.length ?? 0) > 0 && (
                                <div className="gr-config-detail">
                                    <span className="gr-detail-label">PII:</span>
                                    <div className="gr-guard-tags">
                                        {c.settings.pii_entities.map((e) => (
                                            <span key={e} className="gr-item-tag">{piiLabel(e)}</span>
                                        ))}
                                    </div>
                                </div>
                            )}
                            <div className="gr-config-actions">
                                <button className="btn btn-sm" onClick={() => handleToggleActive(c)}>
                                    {c.is_active ? "Disable" : "Enable"}
                                </button>
                                <button className="btn btn-sm" onClick={() => openEdit(c)}>Edit</button>
                                <button className="btn btn-sm btn-danger" onClick={() => handleDelete(c.id)}>Delete</button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
