import { useEffect, useState, useCallback, useMemo, useRef, type KeyboardEvent, type ReactNode } from "react";
import {
    GuardrailsConfig,
    GuardrailsSettings,
    GuardOption,
    GuardParam,
    GuardItemOption,
    OnFailOption,
    listAvailableGuards,
    listGuardOnFailOptions,
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

/** One guard's parameter values, keyed by parameter name. `on_fail` sits next to them. */
type ParamValues = Record<string, unknown>;

/** Contract fallback. The form must not stop when /guardrails/on-fail-options is down. */
const FALLBACK_ON_FAIL: OnFailOption[] = [
    {
        id: "noop",
        label: "Block the request",
        help: "Record the failure and stop the chat turn. Recommended.",
        fixes_text: false,
    },
    {
        id: "exception",
        label: "Block and raise an error",
        help: "Same effect, but the validator raises instead of returning.",
        fixes_text: false,
    },
    {
        id: "fix",
        label: "Repair the text and continue",
        help: "The validator rewrites the text, for example to mask a secret, and the chat turn continues. Only some validators can do this.",
        fixes_text: true,
    },
];

function isEmptyValue(value: unknown): boolean {
    if (value === undefined || value === null || value === "") return true;
    return Array.isArray(value) && value.length === 0;
}

function valueLabel(param: GuardParam, value: unknown): string {
    if (param.type === "select") {
        return param.options?.find((o) => o.id === value)?.label ?? String(value);
    }
    return String(value);
}

/** Values a guard starts with: the catalog defaults plus the default failure action. */
function seedParams(guard: GuardOption): ParamValues {
    const values: ParamValues = { on_fail: "noop" };
    for (const param of guard.params ?? []) values[param.name] = param.default;
    return values;
}

function firstMissingRequired(guard: GuardOption, values: ParamValues): GuardParam | null {
    for (const param of guard.params ?? []) {
        if (param.required && isEmptyValue(values[param.name])) return param;
    }
    return null;
}

/**
 * Payload builder. Only the selected guards reach `selected`, so a guard that the user
 * deselected contributes no key here. Empty values are dropped as well, and the service
 * then applies its own default for that parameter.
 */
function buildSettings(
    selected: GuardOption[],
    values: Record<string, ParamValues>,
): GuardrailsSettings {
    const settings: GuardrailsSettings = {};
    for (const guard of selected) {
        const entry = values[guard.id];
        if (!entry) continue;
        const clean: ParamValues = { on_fail: entry.on_fail ?? "noop" };
        for (const param of guard.params ?? []) {
            const value = entry[param.name];
            if (!isEmptyValue(value)) clean[param.name] = value;
        }
        settings[guard.id] = clean;
    }
    return settings;
}

/** Compact "Label: value" line for a saved value. Returns null for a default or empty value. */
function paramSummary(param: GuardParam, value: unknown): string | null {
    if (isEmptyValue(value) || value === param.default) return null;
    if (Array.isArray(value)) {
        return `${param.label}: ${value.map((v) => valueLabel(param, v)).join(", ")}`;
    }
    if (typeof value === "boolean") return `${param.label}: ${value ? "on" : "off"}`;
    return `${param.label}: ${valueLabel(param, value)}`;
}

function guardSettingRows(guard: GuardOption | undefined, settings: ParamValues | undefined): string[] {
    if (!guard || !settings) return [];
    const rows: string[] = [];
    for (const param of guard.params ?? []) {
        const summary = paramSummary(param, settings[param.name]);
        if (summary) rows.push(summary);
    }
    const onFail = typeof settings.on_fail === "string" ? settings.on_fail : "noop";
    if (onFail !== "noop") rows.push(`On fail: ${onFail}`);
    return rows;
}

interface ParamFieldProps {
    guard: GuardOption;
    param: GuardParam;
    value: unknown;
    onChange: (next: unknown) => void;
}

/** One control per declared parameter type. The catalog decides, not the validator id. */
function ParamField({ guard, param, value, onChange }: ParamFieldProps) {
    const id = `gr-param-${guard.id}-${param.name}`;
    const options = param.options ?? [];
    let control: ReactNode;

    switch (param.type) {
        case "boolean":
            control = (
                <label className="gr-toggle" htmlFor={id}>
                    <input
                        id={id}
                        type="checkbox"
                        checked={value === true}
                        onChange={(e) => onChange(e.target.checked)}
                    />
                    <span>{value === true ? "On" : "Off"}</span>
                </label>
            );
            break;
        case "integer":
        case "number":
            control = (
                <input
                    id={id}
                    className="gr-input"
                    type="number"
                    inputMode="numeric"
                    value={typeof value === "number" ? String(value) : ""}
                    min={param.min ?? undefined}
                    max={param.max ?? undefined}
                    step={param.type === "integer" ? 1 : "any"}
                    onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
                />
            );
            break;
        case "text":
            control = (
                <textarea
                    id={id}
                    className="gr-input gr-textarea"
                    rows={3}
                    value={typeof value === "string" ? value : ""}
                    onChange={(e) => onChange(e.target.value)}
                />
            );
            break;
        case "string_list":
            // The chip control already renders its own label.
            control = (
                <ItemPicker
                    label={param.label}
                    selected={Array.isArray(value) ? value.map((v) => String(v)) : []}
                    options={options}
                    freeText={options.length === 0}
                    allowCustom={guard.allow_custom ?? options.length === 0}
                    placeholder={
                        options.length === 0
                            ? "Type a value and press Enter…"
                            : "Type to match an option…"
                    }
                    onChange={onChange}
                />
            );
            break;
        case "select":
            control = (
                <select
                    id={id}
                    className="gr-select gr-select--block"
                    value={typeof value === "string" ? value : ""}
                    onChange={(e) => onChange(e.target.value)}
                >
                    <option value="">Default</option>
                    {options.map((o) => (
                        <option key={o.id} value={o.id}>{o.label}</option>
                    ))}
                </select>
            );
            break;
        case "string":
        default:
            // Single-line text, plus anything the catalog adds later.
            control = (
                <input
                    id={id}
                    className="gr-input"
                    type="text"
                    value={typeof value === "string" ? value : ""}
                    onChange={(e) => onChange(e.target.value)}
                />
            );
    }

    return (
        <div className="gr-param">
            {param.type !== "string_list" && (
                <label className="gr-param-label" htmlFor={id}>
                    {param.label}
                    {param.required && <span className="gr-req" title="Required">*</span>}
                </label>
            )}
            {control}
            {param.help && <p className="gr-param-help">{param.help}</p>}
        </div>
    );
}

export default function GuardrailsConfigPage() {
    const [configs, setConfigs] = useState<GuardrailsConfig[]>([]);
    const [guards, setGuards] = useState<GuardOption[]>([]);
    const [onFailOptions, setOnFailOptions] = useState<OnFailOption[]>(FALLBACK_ON_FAIL);
    const [loading, setLoading] = useState(true);
    const [catalogError, setCatalogError] = useState<string | null>(null);
    const [configsError, setConfigsError] = useState<string | null>(null);
    const [showForm, setShowForm] = useState(false);

    const [formName, setFormName] = useState("");
    const [formDescription, setFormDescription] = useState("");
    const [formGuards, setFormGuards] = useState<string[]>([]);
    const [formParams, setFormParams] = useState<Record<string, ParamValues>>({});
    const [formMode, setFormMode] = useState("both");
    const [editingId, setEditingId] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setCatalogError(null);
        setConfigsError(null);
        const [guardsResult, configsResult, onFailResult] = await Promise.allSettled([
            listAvailableGuards(),
            listGuardrailsConfigs(),
            listGuardOnFailOptions(),
        ]);
        if (guardsResult.status === "fulfilled") {
            setGuards(guardsResult.value);
        } else {
            setGuards([]);
            setCatalogError(
                guardsResult.reason instanceof Error
                    ? guardsResult.reason.message
                    : "Could not load the validator catalog.",
            );
        }
        if (configsResult.status === "fulfilled") {
            setConfigs(configsResult.value.items);
        } else {
            setConfigsError(
                configsResult.reason instanceof Error
                    ? configsResult.reason.message
                    : "Could not load the saved configurations.",
            );
        }
        if (onFailResult.status === "fulfilled" && onFailResult.value.length > 0) {
            setOnFailOptions(onFailResult.value);
        }
        setLoading(false);
    }, []);

    useEffect(() => { load(); }, [load]);

    const resetForm = () => {
        setFormName("");
        setFormDescription("");
        setFormGuards([]);
        setFormParams({});
        setFormMode("both");
        setEditingId(null);
        setShowForm(false);
        setFormError(null);
    };

    // Selecting a guard seeds its parameters from the catalog defaults. Deselecting
    // removes the guard's entry, so buildSettings() never sends the stale values.
    const toggleGuard = (id: string) => {
        setFormGuards((prev) =>
            prev.includes(id) ? prev.filter((g) => g !== id) : [...prev, id]
        );
        setFormParams((prev) => {
            if (id in prev) {
                const next = { ...prev };
                delete next[id];
                return next;
            }
            const guard = guards.find((g) => g.id === id);
            return guard ? { ...prev, [id]: seedParams(guard) } : prev;
        });
        setFormError(null);
    };

    const setParamValue = (guardId: string, paramName: string, value: unknown) => {
        setFormParams((prev) => ({
            ...prev,
            [guardId]: { ...(prev[guardId] ?? {}), [paramName]: value },
        }));
        setFormError(null);
    };

    const openEdit = (c: GuardrailsConfig) => {
        const saved = c.settings ?? {};
        const seeded: Record<string, ParamValues> = {};
        for (const id of c.guards) {
            const guard = guards.find((g) => g.id === id);
            seeded[id] = { ...(guard ? seedParams(guard) : { on_fail: "noop" }), ...(saved[id] ?? {}) };
        }
        setFormName(c.name);
        setFormDescription(c.description || "");
        setFormGuards([...c.guards]);
        setFormParams(seeded);
        setFormMode(c.mode);
        setEditingId(c.id);
        setShowForm(true);
        setFormError(null);
    };

    const selectedGuards = useMemo(
        () => guards.filter((g) => formGuards.includes(g.id)),
        [guards, formGuards],
    );

    const missingParam = useMemo(() => {
        for (const guard of selectedGuards) {
            const param = firstMissingRequired(guard, formParams[guard.id] ?? {});
            if (param) return { guard, param };
        }
        return null;
    }, [selectedGuards, formParams]);

    const canSave = formName.trim().length > 0 && selectedGuards.length > 0 && !missingParam;

    const requiredMessage = missingParam
        ? `Give "${missingParam.param.label}" a value (${missingParam.guard.label}).`
        : null;

    const handleSave = async () => {
        if (missingParam) {
            setFormError(requiredMessage);
            return;
        }
        if (!formName.trim() || selectedGuards.length === 0) {
            setFormError("Give the config a name and select at least one validator.");
            return;
        }
        setSaving(true);
        setFormError(null);
        const settings = buildSettings(selectedGuards, formParams);
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

    const groupedGuards = useMemo(() => {
        const groups = new Map<string, GuardOption[]>();
        for (const guard of guards) {
            const key = guard.category || "Other";
            const list = groups.get(key);
            if (list) list.push(guard);
            else groups.set(key, [guard]);
        }
        return [...groups.entries()];
    }, [guards]);

    const onFailValue = (guardId: string) => {
        const value = formParams[guardId]?.on_fail;
        return typeof value === "string" && value ? value : "noop";
    };

    const onFailHelp = (guardId: string) =>
        onFailOptions.find((o) => o.id === onFailValue(guardId))?.help ?? "";

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

            {catalogError && (
                <div className="gr-catalog-error">
                    <div>
                        <p className="gr-catalog-error-title">Could not load the validator catalog.</p>
                        <p className="gr-catalog-error-detail">{catalogError}</p>
                    </div>
                    <button type="button" className="btn btn-sm" onClick={() => void load()}>
                        Retry
                    </button>
                </div>
            )}

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

                    {/* The picker and the settings are separate. Showing every validator's
                        parameters at once buried the form under sixteen open panels. */}
                    <div className="gr-form-split">
                        <div className="gr-form-picker">
                            <p className="gr-section-label">
                                Validators
                                <span className="gr-section-count">{groupedGuards.reduce((n, [, items]) => n + items.length, 0)}</span>
                            </p>
                            {groupedGuards.length === 0 && (
                                <p className="gr-param-help">
                                    The service reported no validators. Use Retry above, or check the
                                    guardrails service.
                                </p>
                            )}
                            {groupedGuards.map(([category, items]) => (
                                <div key={category} className="gr-picker-group">
                                    <p className="gr-picker-group-title">
                                        {category}
                                        <span className="gr-picker-group-count">{items.length}</span>
                                    </p>
                                    {items.map((g) => {
                                        const selected = formGuards.includes(g.id);
                                        const disabled = g.available === false;
                                        return (
                                            <label
                                                key={g.id}
                                                className={`gr-picker-chip ${selected ? "selected" : ""} ${disabled ? "gr-picker-chip--unavailable" : ""}`}
                                                title={disabled ? (g.unavailable_reason || "Not installed in the service.") : g.description}
                                            >
                                                <input
                                                    type="checkbox"
                                                    checked={selected}
                                                    disabled={disabled}
                                                    onChange={() => toggleGuard(g.id)}
                                                />
                                                <span className="gr-picker-name">{g.label}</span>
                                                <span className={`gr-tag gr-tag--${g.kind || "local"}`}>{g.kind || "local"}</span>
                                            </label>
                                        );
                                    })}
                                </div>
                            ))}
                        </div>

                        <div className="gr-form-settings">
                            <p className="gr-section-label">
                                Settings
                                <span className="gr-section-count">{selectedGuards.length}</span>
                            </p>

                            {selectedGuards.length === 0 ? (
                                <div className="gr-settings-empty">
                                    <p>No validators selected.</p>
                                    <p className="gr-param-help">
                                        Pick one on the left. Its options appear here.
                                    </p>
                                </div>
                            ) : (
                                selectedGuards.map((g) => (
                                    <div key={g.id} className="gr-setting-card">
                                        <div className="gr-setting-head">
                                            <div>
                                                <span className="gr-setting-name">{g.label}</span>
                                                <span className={`gr-tag gr-tag--${g.kind || "local"}`}>{g.phase || "both"}</span>
                                            </div>
                                            <button
                                                type="button"
                                                className="gr-setting-remove"
                                                onClick={() => toggleGuard(g.id)}
                                                aria-label={`Remove ${g.label}`}
                                            >
                                                Remove
                                            </button>
                                        </div>
                                        <p className="gr-setting-desc">{g.description}</p>

                                        {(g.params ?? []).map((param) => (
                                            <ParamField
                                                key={param.name}
                                                guard={g}
                                                param={param}
                                                value={(formParams[g.id] ?? {})[param.name]}
                                                onChange={(next) => setParamValue(g.id, param.name, next)}
                                            />
                                        ))}

                                        <div className="gr-param">
                                            <label className="gr-param-label" htmlFor={`gr-onfail-${g.id}`}>
                                                Action when the text fails
                                            </label>
                                            <select
                                                id={`gr-onfail-${g.id}`}
                                                className="gr-select gr-select--block"
                                                value={onFailValue(g.id)}
                                                onChange={(e) => setParamValue(g.id, "on_fail", e.target.value)}
                                            >
                                                {onFailOptions.map((o) => (
                                                    <option key={o.id} value={o.id}>{o.label}</option>
                                                ))}
                                            </select>
                                            <p className="gr-param-help">{onFailHelp(g.id)}</p>
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
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

                    {(formError || requiredMessage) && (
                        <p className="gr-form-error" role="alert">
                            {formError || requiredMessage}
                        </p>
                    )}

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

            {configsError && (
                <div className="gr-catalog-error" style={{ marginBottom: "1rem" }}>
                    <p>{configsError}</p>
                    <button type="button" className="btn btn-sm" onClick={() => void load()}>
                        Retry
                    </button>
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
                            <div className="gr-config-guards">
                                {c.guards.map((guardId) => {
                                    const guard = guards.find((g) => g.id === guardId);
                                    const rows = guardSettingRows(guard, c.settings?.[guardId]);
                                    return (
                                        <div key={guardId} className="gr-config-guard">
                                            <div className="gr-guard-tags">
                                                <span className="gr-guard-tag">{guard?.label || guardId}</span>
                                                {rows.length === 0 && (
                                                    <span className="gr-config-guard-hint">
                                                        {guard ? "Default settings" : "Not in the catalog"}
                                                    </span>
                                                )}
                                            </div>
                                            {rows.length > 0 && (
                                                <div className="gr-config-values">
                                                    {rows.map((row) => (
                                                        <span key={row} className="gr-item-tag">{row}</span>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
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
