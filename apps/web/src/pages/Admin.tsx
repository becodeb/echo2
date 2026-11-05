import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ServerDefaultCard } from "./admin/AdminAI";
import { GlobalUsage, PlanRequests, PlansEditor, UserPlans } from "./admin/AdminBilling";
import { AdminOpinion } from "./admin/AdminOpinion";
import { AdminSedes } from "./admin/AdminSedes";
import { AdminUsers } from "./admin/AdminUsers";

const TABS = [
  { id: "organizaciones", label: "Sedes" },
  { id: "usuarios", label: "Usuarios" },
  { id: "opinion", label: "Opinión" },
  { id: "planes", label: "Planes y topes" },
  { id: "pedidos", label: "Pedidos" },
  { id: "consumo", label: "Consumo" },
  { id: "ia", label: "IA" },
] as const;
type Tab = (typeof TABS)[number]["id"];

/**
 * Panel de superadmin: las sedes, todas las personas, lo que opinan, los planes y
 * la IA de la instalación.
 *
 * Es transversal, así que las llamadas van con skipOrg: no hay organización
 * activa que aplique acá, y el superadmin no es miembro de las que administra.
 */
export default function Admin() {
  const [tab, setTabState] = useState<Tab>(() => {
    const hash = window.location.hash.replace("#", "");
    return (TABS.find((item) => item.id === hash)?.id ?? "organizaciones") as Tab;
  });
  // La sede de la que se vino con "Ver sus usuarios".
  const [usersOrg, setUsersOrg] = useState<string | null>(null);
  // Por el router (no con history directo): así un link a otra pestaña del
  // panel (por ejemplo, una notificación de un pedido) con el panel ya abierto
  // también la cambia, aunque la página no se monte de nuevo.
  const navigate = useNavigate();
  const setTab = (next: Tab) => {
    setTabState(next);
    if (next !== "usuarios") setUsersOrg(null);
    navigate({ hash: next }, { replace: true });
  };
  const { hash } = useLocation();
  useEffect(() => {
    const target = TABS.find((item) => item.id === hash.replace("#", ""));
    if (target) setTabState(target.id as Tab);
  }, [hash]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      <h1 className="text-2xl font-semibold tracking-tight text-ink-900">Panel de Becode</h1>
      <nav className="mt-5 flex flex-wrap gap-1 rounded-3xl bg-ink-100 p-1 sm:inline-flex sm:rounded-full" aria-label="Secciones del panel">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            aria-current={tab === item.id ? "page" : undefined}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition-all duration-200 ${
              tab === item.id ? "bg-white text-ink-900 shadow-[0_1px_3px_rgba(0,0,0,0.12)]" : "text-ink-500 hover:text-ink-800"
            }`}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <div key={tab} className="animate-fade-up mt-6">
        {tab === "organizaciones" && (
          <AdminSedes
            onViewUsers={(orgId) => {
              setUsersOrg(orgId);
              setTabState("usuarios");
              navigate({ hash: "usuarios" }, { replace: true });
            }}
          />
        )}
        {tab === "usuarios" && <AdminUsers initialOrg={usersOrg} />}
        {tab === "opinion" && <AdminOpinion />}
        {tab === "planes" && (
          <div className="space-y-4">
            <p className="text-sm text-ink-500">
              Los topes de cada plan. Una organización o una persona pueden tener los suyos (en su tarjeta o en planes
              individuales). Vacío = sin tope.
            </p>
            <PlansEditor />
            <UserPlans />
          </div>
        )}
        {tab === "pedidos" && <PlanRequests />}
        {tab === "consumo" && <GlobalUsage />}
        {tab === "ia" && <ServerDefaultCard />}
      </div>
    </div>
  );
}
