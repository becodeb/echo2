import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./state/auth";
import { Layout } from "./components/Layout";
import { EchoFace } from "./components/EchoFace";
import Login from "./pages/Login";
import Register from "./pages/Register";
import OnboardingOrg from "./pages/OnboardingOrg";
import Dashboard from "./pages/Dashboard";

const MeetingLive = lazy(() => import("./pages/MeetingLive"));
const MeetingDetail = lazy(() => import("./pages/MeetingDetail"));
const Meetings = lazy(() => import("./pages/Meetings"));
const Projects = lazy(() => import("./pages/Projects"));
const ProjectDetail = lazy(() => import("./pages/ProjectDetail"));
const People = lazy(() => import("./pages/People"));
const PersonDetail = lazy(() => import("./pages/PersonDetail"));
const Tasks = lazy(() => import("./pages/Tasks"));
const AskEcho = lazy(() => import("./pages/AskEcho"));
const SearchPage = lazy(() => import("./pages/SearchPage"));
const Settings = lazy(() => import("./pages/Settings"));
const SharedView = lazy(() => import("./pages/SharedView"));
const Admin = lazy(() => import("./pages/Admin"));

function FullLoader() {
  return (
    <div className="flex h-screen items-center justify-center text-ink-300">
      <EchoFace mood="thinking" size={56} />
    </div>
  );
}

export default function App() {
  const { loading, user, organizations } = useAuth();
  const location = useLocation();

  if (location.pathname.startsWith("/s/")) {
    return (
      <Suspense fallback={<FullLoader />}>
        <Routes>
          <Route path="/s/:token" element={<SharedView />} />
        </Routes>
      </Suspense>
    );
  }

  if (loading) return <FullLoader />;

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  if (organizations.length === 0) {
    return <OnboardingOrg />;
  }

  return (
    <Layout>
      <Suspense fallback={<FullLoader />}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/meetings" element={<Meetings />} />
          <Route path="/meetings/:id/live" element={<MeetingLive />} />
          <Route path="/meetings/:id" element={<MeetingDetail />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/people" element={<People />} />
          <Route path="/people/:id" element={<PersonDetail />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/ask" element={<AskEcho />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/settings/*" element={<Settings />} />
          {/* El panel de superadmin no existe para el resto: sin la ruta, /admin
              cae en el catch-all y vuelve al inicio. */}
          {user.is_superadmin && <Route path="/admin" element={<Admin />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}
