import React, { useRef, useState } from "react";

interface ConnectorConfigFormProps {
  connectorType: string;
  config: Record<string, unknown>;
  onConfigChange: (newConfig: Record<string, unknown>) => void;
}

export const defaultConfigFor = (connectorType: string): Record<string, unknown> => {
  switch (connectorType) {
    case "google_drive":
      return { folder_url: "", service_account_json: null };
    case "s3":
      return { bucket: "", access_key_id: "", secret_access_key: "", region: "us-east-1", prefix: "" };
    case "azure_blob":
      return { container_name: "", connection_string: "", prefix: "" };
    case "google_sheets":
      return { spreadsheet_url: "", service_account_json: null };
    case "onedrive":
      return { folder_path: "", client_id: "", client_secret: "", tenant_id: "" };
    case "sharepoint":
      return { site_url: "", folder_path: "", client_id: "", client_secret: "" };
    case "postgres":
    case "postgres_db":
      return { host: "localhost", port: 5432, database: "", username: "", password: "", schema: "public" };
    case "mysql":
    case "mysql_db":
      return { host: "localhost", port: 3306, database: "", username: "", password: "" };
    case "mongodb":
    case "mongodb_db":
      return { connection_uri: "mongodb://localhost:27017", database: "", collection: "" };
    case "web_scraper":
    case "web_crawler":
      return { start_urls: [""], max_depth: 2, max_pages: 100 };
    case "confluence":
      return { domain_url: "", space_key: "", email: "", api_token: "" };
    case "sftp":
      return { host: "", port: 22, username: "", password: "", remote_path: "/" };
    case "http_api":
      return { endpoint_url: "", method: "GET", headers_json: "{}" };
    default:
      return {};
  }
};

export const getConnectorSchema = (_connectorType: string): any => {
  return {};
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "0.65rem 0.85rem",
  borderRadius: "8px",
  border: "1px solid rgba(56, 68, 100, 0.45)",
  background: "rgba(11, 14, 20, 0.6)",
  color: "#e6edf3",
  fontFamily: "inherit",
  fontSize: "0.875rem",
  outline: "none",
  transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
};

const labelStyle: React.CSSProperties = {
  display: "block",
  marginBottom: "0.4rem",
  fontSize: "0.8125rem",
  fontWeight: 600,
  color: "#c9d1d9",
  letterSpacing: "0.01em",
};

const hintStyle: React.CSSProperties = {
  marginTop: "0.35rem",
  fontSize: "0.75rem",
  color: "#8b949e",
  lineHeight: 1.4,
};

const ConnectorConfigForm: React.FC<ConnectorConfigFormProps> = ({
  connectorType,
  config,
  onConfigChange,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [showRawJson, setShowRawJson] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [showPassword, setShowPassword] = useState<Record<string, boolean>>({});

  const [fileName, setFileName] = useState<string | null>(
    (config._filename as string) || null
  );

  const togglePasswordVisibility = (fieldKey: string) => {
    setShowPassword((prev) => ({ ...prev, [fieldKey]: !prev[fieldKey] }));
  };

  const processJsonFile = (file: File) => {
    setErrorMsg(null);
    if (!file.name.toLowerCase().endsWith(".json") && file.type !== "application/json") {
      setErrorMsg("Please select a valid .json file.");
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const text = e.target?.result as string;
        const parsed = JSON.parse(text);
        if (typeof parsed !== "object" || parsed === null) {
          throw new Error("JSON file must contain a JSON object.");
        }
        if (!parsed.private_key && !parsed.client_email && !parsed.type) {
          setErrorMsg("Note: JSON file loaded, but does not appear to be a standard service account key.");
        }
        setFileName(file.name);
        onConfigChange({
          ...config,
          service_account_json: parsed,
          credentials_json: parsed,
          _filename: file.name,
        });
      } catch (err: any) {
        setErrorMsg(`Failed to parse JSON file: ${err.message}`);
      }
    };
    reader.readAsText(file);
  };

  const handleFileDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processJsonFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      processJsonFile(e.target.files[0]);
    }
  };

  const handleRemoveJson = () => {
    setFileName(null);
    const updated = { ...config };
    delete updated.service_account_json;
    delete updated.credentials_json;
    delete updated._filename;
    onConfigChange(updated);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleFieldChange = (key: string, value: unknown) => {
    onConfigChange({ ...config, [key]: value });
  };

  const saJson = (config.service_account_json || config.credentials_json) as Record<string, unknown> | null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      {/* Header Mode Switcher */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          paddingBottom: "0.75rem",
          borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "#e6edf3" }}>
            Configuration Mode
          </span>
          <span
            style={{
              fontSize: "0.7rem",
              padding: "0.15rem 0.5rem",
              borderRadius: "999px",
              background: showRawJson ? "rgba(210, 153, 34, 0.15)" : "rgba(88, 166, 255, 0.15)",
              color: showRawJson ? "#d29922" : "#58a6ff",
              border: `1px solid ${showRawJson ? "rgba(210, 153, 34, 0.3)" : "rgba(88, 166, 255, 0.3)"}`,
              fontWeight: 600,
            }}
          >
            {showRawJson ? "Raw JSON" : "Visual GUI Form"}
          </span>
        </div>

        <button
          type="button"
          onClick={() => setShowRawJson(!showRawJson)}
          style={{
            background: "rgba(255, 255, 255, 0.06)",
            border: "1px solid rgba(255, 255, 255, 0.12)",
            color: "#c9d1d9",
            borderRadius: "6px",
            padding: "0.35rem 0.75rem",
            fontSize: "0.8rem",
            fontWeight: 500,
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: "0.4rem",
            transition: "all 0.15s ease",
          }}
        >
          {showRawJson ? "📋 Switch to GUI Form" : "⚙️ Advanced: Edit Raw JSON"}
        </button>
      </div>

      {errorMsg && (
        <div
          style={{
            padding: "0.75rem 1rem",
            borderRadius: "8px",
            background: "rgba(248, 81, 73, 0.12)",
            border: "1px solid rgba(248, 81, 73, 0.3)",
            color: "#f85149",
            fontSize: "0.8125rem",
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
          }}
        >
          <span>⚠️</span>
          <span>{errorMsg}</span>
        </div>
      )}

      {/* RAW JSON MODE */}
      {showRawJson ? (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
            <label style={labelStyle}>JSON Configuration</label>
            <button
              type="button"
              onClick={() => {
                try {
                  const prettified = JSON.stringify(config, null, 2);
                  onConfigChange(JSON.parse(prettified));
                } catch {
                  // ignore
                }
              }}
              style={{
                fontSize: "0.75rem",
                color: "#58a6ff",
                background: "none",
                border: "none",
                cursor: "pointer",
              }}
            >
              Prettify JSON
            </button>
          </div>
          <textarea
            value={JSON.stringify(config, null, 2)}
            onChange={(e) => {
              try {
                const parsed = JSON.parse(e.target.value);
                onConfigChange(parsed);
                setErrorMsg(null);
              } catch (err: any) {
                setErrorMsg(`Invalid JSON syntax: ${err.message}`);
              }
            }}
            rows={10}
            style={{
              ...inputStyle,
              fontFamily: "var(--font-mono, monospace)",
              fontSize: "0.8125rem",
              lineHeight: 1.5,
              resize: "vertical",
            }}
          />
        </div>
      ) : (
        /* GUI FORM MODE BY CONNECTOR TYPE */
        <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
          {/* GOOGLE DRIVE & GOOGLE SHEETS */}
          {(connectorType === "google_drive" || connectorType === "google_sheets") && (
            <>
              {connectorType === "google_drive" && (
                <div>
                  <label style={labelStyle}>Google Drive Folder URL / Folder ID *</label>
                  <input
                    type="text"
                    value={(config.folder_url as string) || (config.folder_id as string) || ""}
                    onChange={(e) => {
                      const val = e.target.value;
                      handleFieldChange("folder_url", val);
                      handleFieldChange("folder_id", val);
                    }}
                    placeholder="https://drive.google.com/drive/folders/14IXHBDpExTdBd..."
                    style={inputStyle}
                  />
                  <p style={hintStyle}>
                    Paste the full Google Drive folder URL or the 33-character folder ID string.
                  </p>
                </div>
              )}

              {connectorType === "google_sheets" && (
                <div>
                  <label style={labelStyle}>Spreadsheet URL / ID *</label>
                  <input
                    type="text"
                    value={(config.spreadsheet_url as string) || ""}
                    onChange={(e) => handleFieldChange("spreadsheet_url", e.target.value)}
                    placeholder="https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5n..."
                    style={inputStyle}
                  />
                  <p style={hintStyle}>
                    Paste the full Google Spreadsheet URL or unique Spreadsheet ID.
                  </p>
                </div>
              )}

              {/* Service Account JSON File Upload */}
              <div>
                <label style={labelStyle}>Service Account Credentials (.json)</label>
                {saJson || fileName ? (
                  <div
                    style={{
                      padding: "0.85rem 1rem",
                      borderRadius: "8px",
                      background: "rgba(63, 185, 80, 0.1)",
                      border: "1px solid rgba(63, 185, 80, 0.3)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                      <span style={{ fontSize: "1.2rem" }}>🔑</span>
                      <div>
                        <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#3fb950" }}>
                          {fileName || "Service Account Key Loaded"}
                        </div>
                        <div style={{ fontSize: "0.75rem", color: "#8b949e" }}>
                          {saJson?.client_email
                            ? `Email: ${saJson.client_email}`
                            : "Standard service account authentication attached."}
                        </div>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={handleRemoveJson}
                      style={{
                        background: "rgba(248, 81, 73, 0.15)",
                        border: "1px solid rgba(248, 81, 73, 0.3)",
                        color: "#f85149",
                        borderRadius: "6px",
                        padding: "0.3rem 0.6rem",
                        fontSize: "0.75rem",
                        fontWeight: 600,
                        cursor: "pointer",
                      }}
                    >
                      Remove Key
                    </button>
                  </div>
                ) : (
                  <div
                    onDragOver={(e) => {
                      e.preventDefault();
                      setDragOver(true);
                    }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={handleFileDrop}
                    onClick={() => fileInputRef.current?.click()}
                    style={{
                      padding: "1.5rem 1rem",
                      borderRadius: "8px",
                      border: `2px dashed ${dragOver ? "#58a6ff" : "rgba(56, 68, 100, 0.6)"}`,
                      background: dragOver ? "rgba(56, 139, 253, 0.1)" : "rgba(17, 21, 30, 0.4)",
                      textAlign: "center",
                      cursor: "pointer",
                      transition: "all 0.2s ease",
                    }}
                  >
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".json,application/json"
                      onChange={handleFileSelect}
                      style={{ display: "none" }}
                    />
                    <div style={{ fontSize: "1.75rem", marginBottom: "0.4rem" }}>📁</div>
                    <div style={{ fontSize: "0.875rem", fontWeight: 600, color: "#e6edf3" }}>
                      Attach Service Account JSON Key
                    </div>
                    <div style={{ fontSize: "0.75rem", color: "#8b949e", marginTop: "0.25rem" }}>
                      Click to browse or drag and drop your downloaded Google Cloud service account key .json
                    </div>
                  </div>
                )}
              </div>
            </>
          )}

          {/* AMAZON S3 */}
          {connectorType === "s3" && (
            <>
              <div>
                <label style={labelStyle}>S3 Bucket Name *</label>
                <input
                  type="text"
                  value={(config.bucket as string) || ""}
                  onChange={(e) => handleFieldChange("bucket", e.target.value)}
                  placeholder="e.g. my-company-documents-bucket"
                  style={inputStyle}
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                <div>
                  <label style={labelStyle}>AWS Access Key ID *</label>
                  <input
                    type="text"
                    value={(config.access_key_id as string) || ""}
                    onChange={(e) => handleFieldChange("access_key_id", e.target.value)}
                    placeholder="AKIAIOSFODNN7EXAMPLE"
                    style={inputStyle}
                  />
                </div>

                <div>
                  <label style={labelStyle}>AWS Secret Access Key *</label>
                  <div style={{ position: "relative" }}>
                    <input
                      type={showPassword.secret_key ? "text" : "password"}
                      value={(config.secret_access_key as string) || ""}
                      onChange={(e) => handleFieldChange("secret_access_key", e.target.value)}
                      placeholder="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
                      style={{ ...inputStyle, paddingRight: "2.5rem" }}
                    />
                    <button
                      type="button"
                      onClick={() => togglePasswordVisibility("secret_key")}
                      style={{
                        position: "absolute",
                        right: "0.6rem",
                        top: "50%",
                        transform: "translateY(-50%)",
                        background: "none",
                        border: "none",
                        color: "#8b949e",
                        cursor: "pointer",
                        fontSize: "0.85rem",
                      }}
                    >
                      {showPassword.secret_key ? "🙈" : "👁️"}
                    </button>
                  </div>
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                <div>
                  <label style={labelStyle}>AWS Region</label>
                  <select
                    value={(config.region as string) || "us-east-1"}
                    onChange={(e) => handleFieldChange("region", e.target.value)}
                    style={inputStyle}
                  >
                    <option value="us-east-1">us-east-1 (N. Virginia)</option>
                    <option value="us-west-2">us-west-2 (Oregon)</option>
                    <option value="eu-west-1">eu-west-1 (Ireland)</option>
                    <option value="eu-central-1">eu-central-1 (Frankfurt)</option>
                    <option value="ap-south-1">ap-south-1 (Mumbai)</option>
                    <option value="ap-southeast-1">ap-southeast-1 (Singapore)</option>
                  </select>
                </div>

                <div>
                  <label style={labelStyle}>Prefix / Folder Path (Optional)</label>
                  <input
                    type="text"
                    value={(config.prefix as string) || ""}
                    onChange={(e) => handleFieldChange("prefix", e.target.value)}
                    placeholder="e.g. documents/2026/"
                    style={inputStyle}
                  />
                </div>
              </div>
            </>
          )}

          {/* AZURE BLOB */}
          {connectorType === "azure_blob" && (
            <>
              <div>
                <label style={labelStyle}>Container Name *</label>
                <input
                  type="text"
                  value={(config.container_name as string) || ""}
                  onChange={(e) => handleFieldChange("container_name", e.target.value)}
                  placeholder="e.g. enterprise-documents"
                  style={inputStyle}
                />
              </div>

              <div>
                <label style={labelStyle}>Connection String / Account Key *</label>
                <div style={{ position: "relative" }}>
                  <input
                    type={showPassword.azure_conn ? "text" : "password"}
                    value={(config.connection_string as string) || ""}
                    onChange={(e) => handleFieldChange("connection_string", e.target.value)}
                    placeholder="DefaultEndpointsProtocol=https;AccountName=...;AccountKey=..."
                    style={{ ...inputStyle, paddingRight: "2.5rem" }}
                  />
                  <button
                    type="button"
                    onClick={() => togglePasswordVisibility("azure_conn")}
                    style={{
                      position: "absolute",
                      right: "0.6rem",
                      top: "50%",
                      transform: "translateY(-50%)",
                      background: "none",
                      border: "none",
                      color: "#8b949e",
                      cursor: "pointer",
                      fontSize: "0.85rem",
                    }}
                  >
                    {showPassword.azure_conn ? "🙈" : "👁️"}
                  </button>
                </div>
              </div>

              <div>
                <label style={labelStyle}>Prefix / Subfolder (Optional)</label>
                <input
                  type="text"
                  value={(config.prefix as string) || ""}
                  onChange={(e) => handleFieldChange("prefix", e.target.value)}
                  placeholder="e.g. subfolder/path/"
                  style={inputStyle}
                />
              </div>
            </>
          )}

          {/* POSTGRESQL & MYSQL */}
          {(connectorType === "postgres" ||
            connectorType === "postgres_db" ||
            connectorType === "mysql" ||
            connectorType === "mysql_db") && (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "3fr 1fr", gap: "1rem" }}>
                <div>
                  <label style={labelStyle}>Database Host *</label>
                  <input
                    type="text"
                    value={(config.host as string) || "localhost"}
                    onChange={(e) => handleFieldChange("host", e.target.value)}
                    placeholder="localhost or db.company.internal"
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={labelStyle}>Port *</label>
                  <input
                    type="number"
                    value={(config.port as number) || (connectorType.includes("mysql") ? 3306 : 5432)}
                    onChange={(e) => handleFieldChange("port", parseInt(e.target.value, 10))}
                    style={inputStyle}
                  />
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                <div>
                  <label style={labelStyle}>Database Name *</label>
                  <input
                    type="text"
                    value={(config.database as string) || ""}
                    onChange={(e) => handleFieldChange("database", e.target.value)}
                    placeholder="e.g. customer_portal"
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={labelStyle}>Username *</label>
                  <input
                    type="text"
                    value={(config.username as string) || ""}
                    onChange={(e) => handleFieldChange("username", e.target.value)}
                    placeholder="postgres or db_user"
                    style={inputStyle}
                  />
                </div>
              </div>

              <div>
                <label style={labelStyle}>Password *</label>
                <div style={{ position: "relative" }}>
                  <input
                    type={showPassword.db_pass ? "text" : "password"}
                    value={(config.password as string) || ""}
                    onChange={(e) => handleFieldChange("password", e.target.value)}
                    placeholder="••••••••••••"
                    style={{ ...inputStyle, paddingRight: "2.5rem" }}
                  />
                  <button
                    type="button"
                    onClick={() => togglePasswordVisibility("db_pass")}
                    style={{
                      position: "absolute",
                      right: "0.6rem",
                      top: "50%",
                      transform: "translateY(-50%)",
                      background: "none",
                      border: "none",
                      color: "#8b949e",
                      cursor: "pointer",
                      fontSize: "0.85rem",
                    }}
                  >
                    {showPassword.db_pass ? "🙈" : "👁️"}
                  </button>
                </div>
              </div>
            </>
          )}

          {/* MONGODB */}
          {(connectorType === "mongodb" || connectorType === "mongodb_db") && (
            <>
              <div>
                <label style={labelStyle}>Connection URI *</label>
                <input
                  type="text"
                  value={(config.connection_uri as string) || "mongodb://localhost:27017"}
                  onChange={(e) => handleFieldChange("connection_uri", e.target.value)}
                  placeholder="mongodb+srv://user:pass@cluster.mongodb.net"
                  style={inputStyle}
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                <div>
                  <label style={labelStyle}>Database Name *</label>
                  <input
                    type="text"
                    value={(config.database as string) || ""}
                    onChange={(e) => handleFieldChange("database", e.target.value)}
                    placeholder="e.g. analytics_db"
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={labelStyle}>Collection Name</label>
                  <input
                    type="text"
                    value={(config.collection as string) || ""}
                    onChange={(e) => handleFieldChange("collection", e.target.value)}
                    placeholder="e.g. articles"
                    style={inputStyle}
                  />
                </div>
              </div>
            </>
          )}

          {/* WEB SCRAPER / CRAWLER */}
          {(connectorType === "web_scraper" || connectorType === "web_crawler") && (
            <>
              <div>
                <label style={labelStyle}>Start URLs (One per line or comma-separated) *</label>
                <textarea
                  value={
                    Array.isArray(config.start_urls)
                      ? (config.start_urls as string[]).join("\n")
                      : (config.start_urls as string) || ""
                  }
                  onChange={(e) => {
                    const lines = e.target.value
                      .split(/[\n,]/)
                      .map((s) => s.trim())
                      .filter(Boolean);
                    handleFieldChange("start_urls", lines);
                  }}
                  placeholder="https://docs.example.com&#10;https://company.org/blog"
                  rows={3}
                  style={inputStyle}
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                <div>
                  <label style={labelStyle}>Max Crawl Depth (1 - 5)</label>
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={(config.max_depth as number) || 2}
                    onChange={(e) => handleFieldChange("max_depth", parseInt(e.target.value, 10))}
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={labelStyle}>Max Pages Limit</label>
                  <input
                    type="number"
                    value={(config.max_pages as number) || 100}
                    onChange={(e) => handleFieldChange("max_pages", parseInt(e.target.value, 10))}
                    style={inputStyle}
                  />
                </div>
              </div>
            </>
          )}

          {/* FALLBACK FOR UNLISTED CONNECTORS */}
          {!["google_drive", "google_sheets", "s3", "azure_blob", "postgres", "postgres_db", "mysql", "mysql_db", "mongodb", "mongodb_db", "web_scraper", "web_crawler"].includes(connectorType) && (
            <div>
              <p style={{ fontSize: "0.85rem", color: "#8b949e", marginBottom: "0.75rem" }}>
                Configure parameters for <strong>{connectorType}</strong>:
              </p>
              <textarea
                value={JSON.stringify(config, null, 2)}
                onChange={(e) => {
                  try {
                    const parsed = JSON.parse(e.target.value);
                    onConfigChange(parsed);
                  } catch {
                    // ignore
                  }
                }}
                rows={6}
                style={{ ...inputStyle, fontFamily: "monospace" }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ConnectorConfigForm;
