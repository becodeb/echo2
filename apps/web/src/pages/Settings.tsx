import { useEffect, useRef, useState, type ComponentType } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { Icon } from "../components/icons";
import { useAuth } from "../state/auth";
import { useMyAccess } from "../state/access";
import {
  GROUPS,
  canSee,
  resolvePath,
  searchSettings,
  sectionMeta,
  visibleSections,
  type SectionId,
  type Viewer,
} from "./settings/catalog";
import { closeSettings } from "./settings/pageLocation";
import { Loading } from "./settings/parts";
import { AccessSection } from "./settings/AccessSection";
import { NumberingSection, ReasonsSection, TemplateSection } from "./settings/ActaSections";
import { DevicesSection, DictionarySection } from "./settings/AdvancedSections";
import { DriveSection, MyDriveSection } from "./settings/DriveSections";
import { LetterheadSection } from "./settings/LetterheadSection";
import { MyVoiceSection } from "./settings/MyVoiceSection";
import { OrgSection } from "./settings/OrgSection";
import { PrivacySection } from "./settings/PrivacySection";

const SECTION_COMPONENTS: Record<SectionId, ComponentType> = {
  "my-voice": MyVoiceSection,
  "my-drive": MyDriveSection,
  privacy: PrivacySection,
  org: OrgSection,
  access: AccessSection,
  drive: DriveSection,
  template: TemplateSection,
  letterhead: LetterheadSection,
  numbering: NumberingSection,
  reasons: ReasonsSection,
  dictionary: DictionarySection,
  devices: DevicesSection,
};

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';
const DESKTOP = "(min-width: 768px)";

function useIsDesktop() {
  const [desktop, setDesktop] = useState(() => window.matchMedia(DESKTOP).matches);
  useEffect(() => {
    const media = window.matchMedia(DESKTOP);
    const onChange = () => setDesktop(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return desktop;
}

/**
 * Ajustes: una ventana encima de la página, como la de Claude. A la izquierda
 * el buscador y los cuatro grupos; a la derecha la sección. En el celular es
 * pantalla completa: primero la lista y, al tocar, la sección con flecha para
 * volver. La sección va en la URL (/settings/my-drive) para que los links y la
 * vuelta de Google Drive caigan donde corresponde.
 */
export default function Settings() {
  const location = useLocation();
  const navigate = useNavigate();
  const desktop = useIsDesktop();
  const { activeOrg } = useAuth();
  const { data: myAccess, isError } = useMyAccess();

  const roleAdmin = activeOrg?.role === "owner" || activeOrg?.role === "admin";
  const viewer: Viewer | null = myAccess
    ? {
        admin: myAccess.sees_everything || roleAdmin,
        directive: myAccess.rank >= 2,
        managesLevels: myAccess.managed_levels.length > 0,
      }
    : isError
      ? { admin: roleAdmin, directive: false, managesLevels: false }
      : null;

  const resolved = resolvePath(location.pathname.replace(/^\/settings\/?/, "").split("/")[0]);
  const requestedMeta = resolved.section ? sectionMeta(resolved.section) : undefined;
  // Una sección que esta persona no ve abre la ventana como si no hubiera pedido ninguna.
  const requested = requestedMeta && (!viewer || canSee(requestedMeta, viewer)) ? requestedMeta : undefined;
  const sections = viewer ? visibleSections(viewer) : [];
  const active = requested ?? (desktop ? sections[0] : undefined);
  const Section = active ? SECTION_COMPONENTS[active.id] : null;

  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // A qué ajuste saltar dentro de la sección; n cambia en cada salto para repetir el mismo.
  const [jump, setJump] = useState<{ target?: string; n: number }>({ target: resolved.target, n: 0 });
  const [leaving, setLeaving] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const content = useRef<HTMLDivElement>(null);

  const hits = viewer ? searchSettings(query, viewer) : [];

  const close = () => {
    if (leaving) return;
    setLeaving(true);
    window.setTimeout(() => closeSettings(navigate), 140);
  };
  const closeRef = useRef(close);
  closeRef.current = close;

  const open = (id: SectionId, target?: string) => {
    setQuery("");
    setJump((current) => ({ target, n: current.n + 1 }));
    if (id !== requested?.id || location.search) navigate(`/settings/${id}`, { replace: true });
  };

  // Al abrir: foco en el buscador (en el celular no, que saltaría el teclado),
  // Esc cierra, Tab no se escapa de la ventana y la página de atrás no scrollea.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() => {
      if (window.matchMedia(DESKTOP).matches) search.current?.focus();
      else panel.current?.focus();
    });
    const onKey = (event: KeyboardEvent) => {
      // Si hay otra ventana abierta encima (vincular dispositivo), la tecla es de ella.
      const dialogs = document.querySelectorAll('[role="dialog"][aria-modal="true"]');
      if (dialogs[dialogs.length - 1] !== panel.current) return;
      if (event.key === "Escape") {
        closeRef.current();
        return;
      }
      if (event.key !== "Tab" || !panel.current) return;
      const items = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (item) => item.offsetParent !== null,
      );
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
      if (opener && document.contains(opener)) opener.focus();
    };
  }, []);

  // Saltar al ajuste que se eligió en el buscador. La sección puede estar
  // cargando todavía: se reintenta un ratito hasta que aparezca.
  useEffect(() => {
    const box = content.current;
    if (!box) return;
    if (!jump.target) {
      box.scrollTop = 0;
      return;
    }
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let tries = 0;
    let timer = 0;
    const find = () => {
      const element = box.querySelector<HTMLElement>(`[data-setting-id="${jump.target}"]`);
      if (!element) {
        if (++tries < 40) timer = window.setTimeout(find, 75);
        return;
      }
      element.scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });
      if (!reduced) {
        element.animate(
          [{ backgroundColor: "rgba(99, 102, 241, 0.10)" }, { backgroundColor: "rgba(99, 102, 241, 0)" }],
          { duration: 1800, easing: "ease-out" },
        );
      }
    };
    find();
    return () => window.clearTimeout(timer);
  }, [active?.id, jump]);

  useEffect(() => setSelected(0), [query]);

  const navItem = (id: SectionId) => {
    const section = sectionMeta(id)!;
    const current = active?.id === id && (desktop || !!requested);
    return (
      <button
        key={id}
        type="button"
        onClick={() => open(id)}
        aria-current={current ? "page" : undefined}
        className={`flex w-full items-center gap-3 rounded-xl px-2.5 py-3 text-left text-[15px] font-medium transition-colors md:gap-2.5 md:py-[7px] md:text-sm ${
          current ? "bg-ink-100 text-ink-900" : "text-ink-600 hover:bg-ink-100/60 hover:text-ink-900"
        }`}
      >
        <Icon name={section.icon} size={17} />
        <span className="min-w-0 flex-1 truncate">{section.label}</span>
        <span className="rotate-180 text-ink-300 md:hidden">
          <Icon name="chevron-left" size={16} />
        </span>
      </button>
    );
  };

  const groupList = GROUPS.map((group) => {
    const items = sections.filter((section) => section.group === group.id);
    if (!items.length) return null;
    const expanded = !group.collapsed || advancedOpen || items.some((section) => section.id === active?.id);
    return (
      <div key={group.id} className="pt-3 first:pt-0">
        {group.collapsed ? (
          <button
            type="button"
            onClick={() => setAdvancedOpen((value) => !value)}
            aria-expanded={expanded}
            className="flex w-full items-center gap-1 rounded-lg px-2.5 pb-1 pt-1 text-left text-[12px] font-medium text-ink-400 hover:text-ink-700"
          >
            {group.label}
            <span className={`transition-transform duration-200 motion-reduce:transition-none ${expanded ? "-rotate-90" : "rotate-180"}`}>
              <Icon name="chevron-left" size={13} />
            </span>
          </button>
        ) : (
          <p className="px-2.5 pb-1 pt-1 text-[12px] font-medium text-ink-400">{group.label}</p>
        )}
        {expanded && <div className="space-y-0.5">{items.map((section) => navItem(section.id))}</div>}
      </div>
    );
  });

  const closeButton = (className: string) => (
    <button
      type="button"
      onClick={close}
      aria-label="Cerrar ajustes"
      className={`h-10 w-10 shrink-0 items-center justify-center rounded-full text-ink-400 transition-colors hover:bg-ink-100 hover:text-ink-700 ${className}`}
    >
      <Icon name="close" size={18} />
    </button>
  );

  return createPortal(
    <div
      className={`modal-backdrop fixed inset-0 z-50 flex justify-center bg-ink-950/40 backdrop-blur-[2px] md:items-center md:p-6 ${
        leaving ? "modal-leaving" : ""
      }`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label="Ajustes"
        tabIndex={-1}
        className="modal-panel flex h-full w-full overflow-hidden bg-white outline-none md:h-[620px] md:max-h-full md:w-[880px] md:max-w-full md:rounded-3xl md:border md:border-ink-100 md:shadow-2xl"
      >
        {/* Buscador y lista */}
        <aside
          className={`${requested ? "hidden md:flex" : "flex"} w-full shrink-0 flex-col bg-[#fafbfc] md:w-64 md:border-r md:border-ink-100`}
        >
          <div className="flex items-center justify-between gap-2 px-4 pb-3 pt-[max(1rem,env(safe-area-inset-top))] md:px-5 md:pt-5">
            <h2 className="text-xl font-semibold tracking-tight text-ink-900 md:text-[15px]">Ajustes</h2>
            {closeButton("flex md:hidden")}
          </div>
          <div className="px-3 pb-3">
            <label className="flex items-center gap-2 rounded-full border border-ink-200 bg-white px-3 text-ink-400 focus-within:border-accent-500 focus-within:ring-2 focus-within:ring-accent-500/20">
              <Icon name="search" size={16} />
              <input
                ref={search}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    setSelected((index) => Math.min(index + 1, hits.length - 1));
                  } else if (event.key === "ArrowUp") {
                    event.preventDefault();
                    setSelected((index) => Math.max(index - 1, 0));
                  } else if (event.key === "Enter" && hits[selected]) {
                    event.preventDefault();
                    open(hits[selected].section, hits[selected].target);
                  }
                }}
                placeholder="Buscar en ajustes…"
                aria-label="Buscar en ajustes"
                className="min-w-0 flex-1 bg-transparent py-2.5 text-[15px] text-ink-900 outline-none placeholder:text-ink-400 md:py-2 md:text-sm"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => {
                    setQuery("");
                    search.current?.focus();
                  }}
                  aria-label="Borrar búsqueda"
                  className="-mr-1 flex h-7 w-7 items-center justify-center rounded-full hover:bg-ink-100 hover:text-ink-700"
                >
                  <Icon name="close" size={14} />
                </button>
              )}
            </label>
          </div>
          <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-6" aria-label="Secciones de ajustes">
            {!viewer ? (
              <Loading />
            ) : query.trim() ? (
              hits.length ? (
                <ul role="listbox" aria-label="Resultados" className="space-y-0.5">
                  {hits.map((hit, index) => (
                    <li key={`${hit.section}-${hit.target ?? ""}`} role="option" aria-selected={index === selected}>
                      <button
                        type="button"
                        onClick={() => open(hit.section, hit.target)}
                        onMouseEnter={() => setSelected(index)}
                        className={`flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-left md:gap-2.5 md:py-2 ${
                          index === selected ? "bg-ink-100" : ""
                        }`}
                      >
                        <span className="text-ink-500">
                          <Icon name={sectionMeta(hit.section)!.icon} size={17} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[15px] font-medium text-ink-900 md:text-sm">{hit.label}</span>
                          <span className="block truncate text-xs text-ink-400">{hit.where}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="px-3 py-8 text-center text-sm text-ink-400">Nada coincide con «{query.trim()}».</p>
              )
            ) : (
              groupList
            )}
          </nav>
        </aside>

        {/* La sección */}
        <section className={`${requested ? "flex" : "hidden md:flex"} min-w-0 flex-1 flex-col`}>
          <header className="flex items-start gap-1 px-3 pb-1 pt-[max(0.75rem,env(safe-area-inset-top))] md:gap-3 md:px-8 md:pt-7">
            <button
              type="button"
              onClick={() => navigate("/settings", { replace: true })}
              aria-label="Volver a ajustes"
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-ink-600 hover:bg-ink-100 md:hidden"
            >
              <Icon name="chevron-left" size={20} />
            </button>
            <div className="min-w-0 flex-1 pt-1.5 md:pt-0">
              {active && (
                <>
                  <h2 className="text-xl font-semibold tracking-tight text-ink-900 md:text-2xl">{active.label}</h2>
                  <p className="mt-1 text-sm leading-relaxed text-ink-500">{active.description}</p>
                </>
              )}
            </div>
            {closeButton("hidden md:flex -mr-3 -mt-2")}
          </header>
          <div ref={content} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-10 pt-5 md:px-8">
            {Section ? <Section key={active!.id} /> : <Loading />}
          </div>
        </section>
      </div>
    </div>,
    document.body,
  );
}
