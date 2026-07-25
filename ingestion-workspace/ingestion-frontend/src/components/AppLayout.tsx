import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { IconBrowse, IconChat, IconHome, IconIngestion, IconPipeline, IconTracking, IconUpload, IconEvaluation } from "./Icons";
import HomePage from "../pages/HomePage";
import BrowsePage from "../pages/BrowsePage";
import UploadPage from "../pages/UploadPage";
import DirectoryPage from "../pages/DirectoryPage";
import FileViewerPage from "../pages/FileViewerPage";
import PipelinesPage from "../pages/PipelinesPage";
import TrackingPage from "../pages/TrackingPage";
import ChatPage from "../pages/ChatPage";
import EvaluationsPage from "../pages/EvaluationsPage";
import GoldenEvaluationsPage from "../pages/GoldenEvaluationsPage";

const NAV: { to: string; label: string; icon: typeof IconHome; end?: boolean }[] = [
  { to: "/", label: "Overview", icon: IconHome, end: true },
  { to: "/browse", label: "Folders", icon: IconBrowse },
  { to: "/upload", label: "Upload", icon: IconUpload },
  { to: "/pipelines", label: "Pipelines", icon: IconPipeline },
  { to: "/chat", label: "Chat", icon: IconChat },
  { to: "/evaluations", label: "Live Chat Metrics", icon: IconEvaluation },
  { to: "/golden-evaluations", label: "Offline Evaluation", icon: IconEvaluation },
  { to: "/tracking", label: "Tracking", icon: IconTracking },
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

export default function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const path = location.pathname;
  const params = useRouteParams(path);
  const { theme, toggle: toggleTheme } = useTheme();

  const isHome = path === "/";
  const isBrowseExact = path === "/browse" || path === "/directories";
  const isUpload = path === "/upload";
  const isPipelines = path === "/pipelines";
  const isChat = path === "/chat";
  const isEvaluations = path === "/evaluations";
  const isGoldenEvaluations = path === "/golden-evaluations";
  const isTracking = path === "/tracking";
  const isDirectory = params.type === "directory";
  const isViewer = params.type === "viewer";

  return (
    <div className="shell">
      <aside className="sidebar">
        <NavLink to="/" className="sidebar-brand" end>
          <IconIngestion className="brand-icon" />
          <span>Ingestion</span>
        </NavLink>

        <nav className="sidebar-nav" aria-label="Main">
          <p className="sidebar-section">Workspace</p>
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}
            >
              <Icon className="sidebar-link-icon" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Theme Toggle */}
        <div style={{ padding: "0.75rem 0.625rem" }}>
          <button className="theme-toggle" onClick={toggleTheme} title="Toggle theme">
            <span className="theme-toggle-icon">{theme === "dark" ? "☀️" : "🌙"}</span>
            {theme === "dark" ? "Light Mode" : "Dark Mode"}
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

        <PersistentPage visible={isUpload}>
          <UploadPage />
        </PersistentPage>

        <PersistentPage visible={isPipelines}>
          <PipelinesPage />
        </PersistentPage>

        <PersistentPage visible={isChat}>
          <ChatPage />
        </PersistentPage>

        <PersistentPage visible={isEvaluations}>
          <EvaluationsPage />
        </PersistentPage>

        <PersistentPage visible={isGoldenEvaluations}>
          <GoldenEvaluationsPage />
        </PersistentPage>

        <PersistentPage visible={isTracking}>
          <TrackingPage />
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
      </div>
    </div>
  );
}

