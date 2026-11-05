import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { IconChat, IconChevronRight, IconGuardrails, IconHome, IconIngestion, IconPipeline, IconPrompts, IconEvaluation, IconSparkles } from "./Icons";
import HomePage from "../pages/HomePage";
import BrowsePage from "../pages/BrowsePage";
import UploadPage from "../pages/UploadPage";
import DirectoryPage from "../pages/DirectoryPage";
import FileViewerPage from "../pages/FileViewerPage";
import PipelinesPage from "../pages/PipelinesPage";
import ChatPage from "../pages/ChatPage";
import EvaluationsPage from "../pages/EvaluationsPage";
import EvalRunDetailPage from "../pages/EvalRunDetailPage";
import GoldenEvaluationsPage from "../pages/GoldenEvaluationsPage";
import DatasetFabricPage from "../pages/DatasetFabricPage";
import DatasetFeedbackPage from "../pages/DatasetFeedbackPage";
import SyntheticDatasetPage from "../pages/SyntheticDatasetPage";
import PromptsPage from "../pages/PromptsPage";
import GuardrailsConfigPage from "../pages/GuardrailsConfigPage";
import GuardrailsTracesPage from "../pages/GuardrailsTracesPage";
import GuardrailsEvaluationPage from "../pages/GuardrailsEvaluationPage";
import SourcesPage from "../pages/SourcesPage";
import SourceDetailPage from "../pages/SourceDetailPage";
import KnowledgeStorePage from "../pages/KnowledgeStorePage";
import KnowledgeProductPage from "../pages/KnowledgeProductPage";
import { IconBucket, IconDatabase } from "./Icons";

const NAV: { to: string; label: string; icon: typeof IconHome; end?: boolean }[] = [
  { to: "/", label: "Overview", icon: IconHome, end: true },
  { to: "/knowledge-store", label: "Knowledge Store", icon: IconDatabase },
  { to: "/pipelines", label: "Pipelines", icon: IconPipeline },
  { to: "/chat", label: "Chat", icon: IconChat },
  { to: "/prompts", label: "Prompts", icon: IconPrompts },
  { to: "/evaluations", label: "Real Time Monitoring", icon: IconEvaluation },
  { to: "/dataset-fabric", label: "Dataset Fabric", icon: IconBucket },
  { to: "/dataset-feedback", label: "Dataset Feedback", icon: IconSparkles },
  { to: "/synthetic-datasets", label: "Synthetic Datasets", icon: IconSparkles },
  { to: "/golden-evaluations", label: "Offline Evaluation", icon: IconEvaluation },
  { to: "/guardrails/config", label: "Guard Config", icon: IconGuardrails },
  { to: "/guardrails/traces", label: "Guard Traces", icon: IconGuardrails },
  { to: "/guardrails/evaluation", label: "Guard Evaluation", icon: IconGuardrails },
];

/**
 * Persistent page wrapper: pages are always mounted, only the active
 * one is visible. This preserves component state (running pipelines,
 * in-progress uploads, form fields) across navigation.
 */
function PersistentPage({
  visible,
  children,
}: {
  visible: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`persistent-page${visible ? " persistent-page--active" : ""}`}
      aria-hidden={!visible}
    >
      {children}
    </div>
  );
}

/** Extract route params from pathname since pages aren't inside <Route> */
function useRouteParams(path: string) {
  return useMemo(() => {
    // /browse/:name/view/:fileId
    const viewMatch = path.match(/^\/browse\/([^/]+)\/view\/([^/]+)/);
    if (viewMatch) return { name: viewMatch[1], fileId: viewMatch[2], type: "viewer" as const };

    // /directories/:name/view/:fileId (legacy)
    const legacyViewMatch = path.match(/^\/directories\/([^/]+)\/view\/([^/]+)/);
    if (legacyViewMatch) return { name: legacyViewMatch[1], fileId: legacyViewMatch[2], type: "viewer" as const };

    // /files/:id/view (legacy)
    const filesViewMatch = path.match(/^\/files\/([^/]+)\/view/);
    if (filesViewMatch) return { name: undefined, fileId: filesViewMatch[1], type: "viewer" as const };

    // /browse/:name
    const dirMatch = path.match(/^\/browse\/([^/]+)\/?$/);
    if (dirMatch) return { name: dirMatch[1], type: "directory" as const };

    // /directories/:name (legacy)
    const legacyDirMatch = path.match(/^\/directories\/([^/]+)\/?$/);
    if (legacyDirMatch) return { name: legacyDirMatch[1], type: "directory" as const };
    // /sources/:id
    const sourceMatch = path.match(/^\/sources\/([^/]+)\/?$/);
    if (sourceMatch) return { id: sourceMatch[1], type: "source-detail" as const };

    // /knowledge-store/:id
    const knowledgeProductMatch = path.match(/^\/knowledge-store\/([^/]+)\/?$/);
    if (knowledgeProductMatch) return { id: knowledgeProductMatch[1], type: "knowledge-product" as const };

    return { type: "none" as const };
  }, [path]);
}

function useTheme() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const stored = localStorage.getItem("app-theme");
    return stored === "light" ? "light" : "dark";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("app-theme", theme);
  }, [theme]);

  const toggle = () => setTheme((prev) => (prev === "dark" ? "light" : "dark"));

  return { theme, toggle };
}

/**
 * The sidebar keeps its own collapsed state, so it survives a page reload and stays
 * collapsed while the user moves between pages.
 */
function useSidebar() {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("sidebar-collapsed") === "1");

  useEffect(() => {
    localStorage.setItem("sidebar-collapsed", collapsed ? "1" : "0");
  }, [collapsed]);

  return { collapsed, toggle: () => setCollapsed((prev) => !prev) };
}

export default function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const path = location.pathname;
  const params = useRouteParams(path);
  const { theme, toggle: toggleTheme } = useTheme();
  const { collapsed, toggle: toggleSidebar } = useSidebar();

  const isHome = path === "/";
  const isBrowseExact = path === "/browse" || path === "/directories";
  const isSourcesExact = path === "/sources";
  const isKnowledgeStore = path === "/knowledge-store";
  const isUpload = path === "/upload";
  const isPipelines = path === "/pipelines";
  const isChat = path === "/chat";
  const isPrompts = path === "/prompts";
  const isEvaluations = path === "/evaluations";
  const isDatasetFabric = path === "/dataset-fabric";
  const isDatasetFeedback = path === "/dataset-feedback";
  const isSyntheticDatasets = path === "/synthetic-datasets";
  const isGoldenEvaluations = path === "/golden-evaluations";
  // The run detail page lives under the evaluation page, so it must be matched before the
  // exact comparison below and must not also switch the evaluation page on.
  const isEvalRunDetail = /^\/golden-evaluations\/runs\/[^/]+/.test(path);
  const isGuardrailsConfig = path === "/guardrails/config";
  const isGuardrailsTraces = path === "/guardrails/traces";
  const isGuardrailsEvaluation = path === "/guardrails/evaluation";
  const isDirectory = params.type === "directory";
  const isViewer = params.type === "viewer";
  const isSourceDetail = params.type === "source-detail";
  const isKnowledgeProduct = params.type === "knowledge-product";

  return (
    <div className={`shell${collapsed ? " shell--collapsed" : ""}`}>
      <aside className="sidebar" id="app-sidebar" aria-label="Workspace">
        <div className="sidebar-head">
          <NavLink to="/" className="sidebar-brand" end title="Overview">
            <IconIngestion className="brand-icon" />
            <span className="sidebar-label">Retrieval & Chat</span>
          </NavLink>
          <button
            type="button"
            className="sidebar-toggle"
            onClick={toggleSidebar}
            aria-expanded={!collapsed}
            aria-controls="app-sidebar"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <span className="sidebar-toggle-glyph">
              <IconChevronRight size={14} />
            </span>
          </button>
        </div>

        <nav className="sidebar-nav" aria-label="Main">
          <p className="sidebar-section">Workspace</p>
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              title={collapsed ? label : undefined}
              aria-label={label}
              className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}
            >
              <Icon className="sidebar-link-icon" />
              <span className="sidebar-label">{label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Theme Toggle */}
        <div style={{ padding: "0.75rem 0.625rem" }}>
          <button
            className="theme-toggle"
            onClick={toggleTheme}
            title="Toggle theme"
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            <span className="theme-toggle-icon">{theme === "dark" ? "☀️" : "🌙"}</span>
            <span className="sidebar-label">{theme === "dark" ? "Light Mode" : "Dark Mode"}</span>
          </button>
        </div>
      </aside>

      <div className="shell-body">
        {/* ── Persistent top-level pages ── */}
        <PersistentPage visible={isHome}>
          <HomePage />
        </PersistentPage>

        <PersistentPage visible={isBrowseExact}>
          <BrowsePage />
        </PersistentPage>
        <PersistentPage visible={isSourcesExact}>
          <SourcesPage />
        </PersistentPage>

        <PersistentPage visible={isKnowledgeStore}>
          <KnowledgeStorePage />
        </PersistentPage>

        <PersistentPage visible={isUpload}>
          <UploadPage />
        </PersistentPage>

        <PersistentPage visible={isPipelines}>
          <PipelinesPage />
        </PersistentPage>

        <PersistentPage visible={isChat}>
          <ChatPage />
        </PersistentPage>

        <PersistentPage visible={isPrompts}>
          <PromptsPage />
        </PersistentPage>

        <PersistentPage visible={isEvaluations}>
          <EvaluationsPage />
        </PersistentPage>

        <PersistentPage visible={isDatasetFabric}>
          <DatasetFabricPage />
        </PersistentPage>

        <PersistentPage visible={isDatasetFeedback}>
          <DatasetFeedbackPage />
        </PersistentPage>

        <PersistentPage visible={isSyntheticDatasets}>
          <SyntheticDatasetPage />
        </PersistentPage>

        <PersistentPage visible={isGoldenEvaluations}>
          <GoldenEvaluationsPage />
        </PersistentPage>

        <PersistentPage visible={isEvalRunDetail}>
          <EvalRunDetailPage />
        </PersistentPage>

        <PersistentPage visible={isGuardrailsConfig}>
          <GuardrailsConfigPage />
        </PersistentPage>

        <PersistentPage visible={isGuardrailsTraces}>
          <GuardrailsTracesPage />
        </PersistentPage>

        <PersistentPage visible={isGuardrailsEvaluation}>
          <GuardrailsEvaluationPage />
        </PersistentPage>

        {/* Dynamic-param pages: re-mount when params change via key */}
        {isDirectory && params.name && (
          <PersistentPage visible={true}>
            <DirectoryPage routeName={params.name} routeNavigate={navigate} />
          </PersistentPage>
        )}

        {isViewer && params.fileId && (
          <PersistentPage visible={true}>
            <FileViewerPage
              routeDir={params.name}
              routeFileId={params.fileId}
              routeNavigate={navigate}
            />
          </PersistentPage>
        )}
        {isSourceDetail && params.id && (
          <PersistentPage visible={true}>
            <SourceDetailPage key={params.id} routeSourceId={params.id} />
          </PersistentPage>
        )}
        {isKnowledgeProduct && params.id && (
          <PersistentPage visible={true}>
            <KnowledgeProductPage key={params.id} routeProductId={params.id} />
          </PersistentPage>
        )}
      </div>
    </div>
  );
}

