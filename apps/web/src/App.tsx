import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./state/auth";
import { useMyAccess } from "./state/access";
import { Layout } from "./components/Layout";
import { EchoFace } from "./components/EchoFace";
import Login from "./pages/Login";
import Register from "./pages/Register";
import OnboardingOrg from "./pages/OnboardingOrg";
import Dashboard from "./pages/Dashboard";

const loadMeetingLive = () => import("./pages/MeetingLive");
const MeetingLive = lazy(loadMeetingLive);
const loadMeetingDetail = () => import("./pages/MeetingDetail");
const MeetingDetail = lazy(loadMeetingDetail);
const loadMeetings = () => import("./pages/Meetings");
const Meetings = lazy(loadMeetings);
const loadInternalMeetings = () => import("./pages/InternalMeetings");
const InternalMeetings = lazy(loadInternalMeetings);
const loadProjects = () => import("./pages/Projects");
const Projects = lazy(loadProjects);
const loadProjectDetail = () => import("./pages/ProjectDetail");
const ProjectDetail = lazy(loadProjectDetail);
const loadPeople = () => import("./pages/People");
const People = lazy(loadPeople);
const loadPersonDetail = () => import("./pages/PersonDetail");
const PersonDetail = lazy(loadPersonDetail);
const loadTasks = () => import("./pages/Tasks");
const Tasks = lazy(loadTasks);
const loadAskEcho = () => import("./pages/AskEcho");
const AskEcho = lazy(loadAskEcho);
const loadSearchPage = () => import("./pages/SearchPage");
const SearchPage = lazy(loadSearchPage);
const loadSettings = () => import("./pages/Settings");
const Settings = lazy(loadSettings);
const loadSharedView = () => import("./pages/SharedView");
const SharedView = lazy(loadSharedView);
const loadAdmin = () => import("./pages/Admin");
const Admin = lazy(loadAdmin);
const loadFamilies = () => import("./pages/Families");
const Families = lazy(loadFamilies);
const loadReports = () => import("./pages/Reports");
const Reports = lazy(loadReports);
const loadLanding = () => import("./pages/Landing");
const Landing = lazy(loadLanding);
const loadActaPrint = () => import("./pages/ActaPrint");
const ActaPrint = lazy(loadActaPrint);
const loadChooseLevel = () => import("./pages/ChooseLevel");
const ChooseLevel = lazy(loadChooseLevel);
const loadPlans = () => import("./pages/Plans");
const Plans = lazy(loadPlans);
const loadUsage = () => import("./pages/Usage");
const Usage = lazy(loadUsage);
const loadLegal = () => import("./pages/Legal");
const Legal = lazy(loadLegal);
const loadContact = () => import("./pages/Contact");
const Contact = lazy(loadContact);

// Las páginas se bajan de a una la primera vez que se abren, y mientras tanto
// la pantalla quedaba vacía: al cambiar de sección "se teletransportaba". Con
// la sesión abierta se bajan todas en segundo plano, así cambiar es inmediato.
const PAGE_LOADERS = [loadMeetingLive, loadMeetingDetail, loadMeetings, loadInternalMeetings, loadProjects, loadProjectDetail, loadPeople, loadPersonDetail, loadTasks, loadAskEcho, loadSearchPage, loadSettings, loadAdmin, loadFamilies, loadReports, loadChooseLevel, loadPlans, loadUsage, loadLegal];

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
  const myAccess = useMyAccess();

  useEffect(() => {
    if (!user) return;
    const prefetch = () => PAGE_LOADERS.forEach((load) => void load().catch(() => {}));
    const idle = (window as Window & { requestIdleCallback?: (cb: () => void, options?: { timeout: number }) => number })
      .requestIdleCallback;
    // Con tope: en una pestaña de fondo el navegador puede no estar nunca "ocioso".
    if (idle) idle(prefetch, { timeout: 4000 });
    else window.setTimeout(prefetch, 1500);
  }, [user]);

  if (location.pathname.startsWith("/s/")) {
    return (
      <Suspense fallback={<FullLoader />}>
        <Routes>
          <Route path="/s/:token" element={<SharedView />} />
        </Routes>
      </Suspense>
    );
  }

  // Privacidad, términos y contacto: públicos, con o sin sesión.
  if (location.pathname.startsWith("/legal") || location.pathname === "/contacto") {
    return (
      <Suspense fallback={<div className="min-h-dvh bg-[#fafbfc]" />}>
        <Routes>
          <Route path="/legal/:doc" element={<Legal />} />
          <Route path="/contacto" element={<Contact />} />
          <Route path="*" element={<Navigate to="/legal/privacidad" replace />} />
        </Routes>
      </Suspense>
    );
  }

  // Las rutas viejas de la landing viven ahora en la raíz.
  if (location.pathname.startsWith("/landing")) {
    return <Navigate to="/" replace />;
  }

  // Sin sesión, la raíz es la landing pública. Mientras se resuelve el refresh
  // se muestra negro (igual que el primer frame del video), así quien sí tiene
  // sesión pasa al panel sin ver arrancar la apertura.
  if (!user && location.pathname === "/") {
    if (loading) return <div className="min-h-[100dvh] bg-ink-950" />;
    return (
      <Suspense fallback={<div className="min-h-[100dvh] bg-ink-950" />}>
        <Landing />
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

  // Recién entrado a la sede y sin nivel: primero dice de qué nivel es.
  if (myAccess.isLoading) return <FullLoader />;
  if (myAccess.data?.needs_level) {
    return (
      <Suspense fallback={<FullLoader />}>
        <ChooseLevel />
      </Suspense>
    );
  }

  // La hoja del acta para imprimir va sin el marco de la app.
  if (/^\/meetings\/[^/]+\/acta$/.test(location.pathname)) {
    return (
      <Suspense fallback={<FullLoader />}>
        <Routes>
          <Route path="/meetings/:id/acta" element={<ActaPrint />} />
        </Routes>
      </Suspense>
    );
  }

  return (
    <Layout>
      {/* Sin la carita a pantalla completa: dentro del marco, un instante en blanco
          se ve como parte de la transición. */}
      <Suspense fallback={<div className="h-full" />}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/meetings" element={<Meetings />} />
          <Route path="/internal" element={<InternalMeetings />} />
          <Route path="/meetings/:id/live" element={<MeetingLive />} />
          <Route path="/meetings/:id" element={<MeetingDetail />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/people" element={<People />} />
          <Route path="/families" element={<Families />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/people/:id" element={<PersonDetail />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/ask" element={<AskEcho />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/settings/*" element={<Settings />} />
          <Route path="/plans" element={<Plans />} />
          <Route path="/usage" element={<Usage />} />
          {/* El panel de superadmin no existe para el resto: sin la ruta, /admin
              cae en el catch-all y vuelve al inicio. */}
          {user.is_superadmin && <Route path="/admin" element={<Admin />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}
