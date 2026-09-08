import { Navigate, Route, Routes, useParams } from "react-router-dom";
import AppLayout from "./components/AppLayout";

function LegacyFolderRedirect() {
  const { name } = useParams<{ name: string }>();
  return <Navigate to={`/browse/${name}`} replace />;
}

function LegacyViewerRedirect() {
  const { name, fileId } = useParams<{ name: string; fileId: string }>();
  return <Navigate to={`/browse/${name}/view/${fileId}`} replace />;
}

/**
 * AppLayout now handles rendering persistent pages internally.
 * The Routes here only exist for legacy redirects.
 * The wildcard "*" ensures AppLayout always renders regardless of path.
 */
export default function App() {
  return (
    <Routes>
      {/* Legacy redirects */}
      <Route path="directories" element={<Navigate to="/browse" replace />} />
      <Route path="directories/:name" element={<LegacyFolderRedirect />} />
      <Route path="directories/:name/view/:fileId" element={<LegacyViewerRedirect />} />
      {/* Catch-all renders the persistent layout */}
      <Route path="*" element={<AppLayout />} />
    </Routes>
  );
}
