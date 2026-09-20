import { useMemo, useState } from "react"
import type { KnowledgeDestinationField, KnowledgeDestinationOption, LiteLLMModelOption } from "../api"

type DestinationConfigFieldsProps = {
  option: KnowledgeDestinationOption
  config: Record<string, unknown>
  litellmModels: LiteLLMModelOption[]
  onChange: (nextConfig: Record<string, unknown>) => void
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "6px 10px",
  borderRadius: "6px",
  background: "rgba(15, 23, 42, 0.8)",
  border: "1px solid rgba(255, 255, 255, 0.1)",
  color: "#e2e8f0",
  fontSize: "12px",
}

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: "11px",
  color: "#94a3b8",
  marginBottom: "4px",
}

const hintStyle: React.CSSProperties = {
  fontSize: "10px",
  color: "#64748b",
  marginTop: "2px",
}

const coerceValue = (field: KnowledgeDestinationField, raw: string): unknown => {
  if (field.type === "boolean") return raw === "true"
  if (field.type === "number") {
    // Number("") is 0, which would store a zero when the user clears the field.
    if (raw.trim() === "") return ""
    const parsed = Number(raw)
    return Number.isNaN(parsed) ? raw : parsed
  }
  return raw
}

const renderValue = (value: unknown): string => {
  if (typeof value === "boolean") return value ? "true" : "false"
  if (value === null || value === undefined) return ""
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

export default function DestinationConfigFields({
  option,
  config,
  litellmModels,
  onChange,
}: DestinationConfigFieldsProps) {
  const [showAdvanced, setShowAdvanced] = useState(false)

  const groupedFields = useMemo(() => {
    const fields = option.fields || []
    const visible = fields.filter((field) => showAdvanced || !field.advanced)
    const groups = new Map<string, KnowledgeDestinationField[]>()
    for (const field of visible) {
      const group = field.group || "General"
      const current = groups.get(group) || []
      current.push(field)
      groups.set(group, current)
    }
    return Array.from(groups.entries())
  }, [option.fields, showAdvanced])

  const modelsForField = (field: KnowledgeDestinationField): LiteLLMModelOption[] => {
    if (!field.model_kind) return litellmModels
    const filtered = litellmModels.filter((model) => model.kind === field.model_kind)
    return filtered.length > 0 ? filtered : litellmModels
  }

  const handleFieldChange = (field: KnowledgeDestinationField, raw: string) => {
    onChange({
      ...config,
      [field.key]: coerceValue(field, raw),
    })
  }

  const hasAdvanced = (option.fields || []).some((field) => field.advanced)

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
      {hasAdvanced && (
        <button
          type="button"
          onClick={() => setShowAdvanced((prev) => !prev)}
          style={{
            alignSelf: "flex-start",
            background: "rgba(59, 130, 246, 0.12)",
            border: "1px solid rgba(59, 130, 246, 0.25)",
            color: "#93c5fd",
            borderRadius: "8px",
            padding: "4px 10px",
            fontSize: "11px",
            cursor: "pointer",
          }}
        >
          {showAdvanced ? "Hide advanced settings" : "Show advanced settings"}
        </button>
      )}

      {groupedFields.map(([group, fields]) => (
        <div key={group}>
          <div
            style={{
              fontSize: "11px",
              fontWeight: 700,
              color: "#38bdf8",
              textTransform: "uppercase",
              marginBottom: "8px",
            }}
          >
            {group}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
            {fields.map((field) => {
              const value = config[field.key]
              const fieldId = `${option.id}-${field.key}`

              if (field.type === "boolean") {
                return (
                  <label key={field.key} style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer" }}>
                    <input
                      id={fieldId}
                      type="checkbox"
                      checked={Boolean(value)}
                      onChange={(e) => handleFieldChange(field, e.target.checked ? "true" : "false")}
                    />
                    <span style={{ fontSize: "12px", color: "#e2e8f0" }}>{field.label}</span>
                  </label>
                )
              }

              if (field.type === "select") {
                return (
                  <div key={field.key}>
                    <label htmlFor={fieldId} style={labelStyle}>
                      {field.label}
                      {field.required ? " *" : ""}
                    </label>
                    <select
                      id={fieldId}
                      value={renderValue(value)}
                      onChange={(e) => handleFieldChange(field, e.target.value)}
                      style={inputStyle}
                    >
                      {(field.options || []).map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                    {field.description && <div style={hintStyle}>{field.description}</div>}
                  </div>
                )
              }

              if (field.type === "model") {
                const models = modelsForField(field)
                const currentValue = renderValue(value)
                if (models.length === 0) {
                  return (
                    <div key={field.key}>
                      <label htmlFor={fieldId} style={labelStyle}>
                        {field.label}
                        {field.required ? " *" : ""}
                      </label>
                      <input
                        id={fieldId}
                        type="text"
                        value={currentValue}
                        placeholder={field.placeholder || "LiteLLM model name"}
                        onChange={(e) => handleFieldChange(field, e.target.value)}
                        style={inputStyle}
                      />
                      {field.description && <div style={hintStyle}>{field.description}</div>}
                    </div>
                  )
                }
                return (
                  <div key={field.key}>
                    <label htmlFor={fieldId} style={labelStyle}>
                      {field.label}
                      {field.required ? " *" : ""}
                    </label>
                    <select
                      id={fieldId}
                      value={currentValue}
                      onChange={(e) => handleFieldChange(field, e.target.value)}
                      style={inputStyle}
                    >
                      {currentValue && !models.some((model) => model.id === currentValue) && (
                        <option value={currentValue}>{currentValue}</option>
                      )}
                      {models.map((model) => (
                        <option key={model.id} value={model.id}>{model.id}</option>
                      ))}
                    </select>
                    {field.description && <div style={hintStyle}>{field.description}</div>}
                  </div>
                )
              }

              return (
                <div key={field.key}>
                  <label htmlFor={fieldId} style={labelStyle}>
                    {field.label}
                    {field.required ? " *" : ""}
                  </label>
                  <input
                    id={fieldId}
                    type={field.type === "password" ? "password" : field.type === "number" ? "number" : "text"}
                    min={field.min ?? undefined}
                    max={field.max ?? undefined}
                    // Without this the browser applies step=1 and refuses a
                    // fractional value such as BM25 k1 1.2 or b 0.75.
                    step={field.type === "number" ? "any" : undefined}
                    value={renderValue(value)}
                    placeholder={field.placeholder || ""}
                    onChange={(e) => handleFieldChange(field, e.target.value)}
                    style={inputStyle}
                  />
                  {field.description && <div style={hintStyle}>{field.description}</div>}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
