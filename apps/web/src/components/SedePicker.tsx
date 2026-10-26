import { useAuth } from "../state/auth";

/** "Northfield Nordelta" y "Northfield Puertos" → "Nordelta" y "Puertos". */
function shortNames(names: string[]): string[] {
  const first = names.map((name) => name.split(" ")[0]);
  const shared = first.every((word) => word === first[0]) && names.every((name) => name.includes(" "));
  return shared ? names.map((name) => name.slice(name.indexOf(" ") + 1)) : names;
}

/**
 * Para quien está en más de una sede: de qué sede es la reunión, o si es
 * intersede. Decide el formato del acta (el de la sede, o ninguno). Elegir la
 * otra sede cambia de sede y vuelve a abrir "Nueva reunión" allá, con sus
 * familias y su formato.
 */
export function SedePicker({ intersede, onIntersede }: { intersede: boolean; onIntersede: (value: boolean) => void }) {
  const { organizations, activeOrg, switchOrg } = useAuth();
  const sedes = organizations.filter((org) => !org.is_personal);
  if (sedes.length < 2 || !activeOrg) return null;
  const labels = shortNames(sedes.map((sede) => sede.name));
  const options = [
    ...sedes.map((sede, index) => ({ value: sede.id, label: labels[index] })),
    { value: "intersede", label: "Intersede" },
  ];
  const value = intersede ? "intersede" : activeOrg.id;

  return (
    <div>
      <span className="mb-1.5 block text-sm font-medium text-ink-700">¿De qué sede es la reunión?</span>
      <div role="radiogroup" aria-label="De qué sede es la reunión" className="flex flex-wrap gap-1.5">
        {options.map((option) => {
          const on = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => {
                if (option.value === "intersede") return onIntersede(true);
                if (option.value === activeOrg.id) return onIntersede(false);
                switchOrg(option.value);
                window.location.href = "/meetings?new=1";
              }}
              className={`min-h-10 rounded-full border px-4 py-1.5 text-sm font-medium transition-colors ${
                on ? "border-ink-900 bg-ink-900 text-white" : "border-ink-200 bg-white text-ink-700 hover:border-ink-300"
              }`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
      <p className="mt-1.5 text-xs text-ink-400">
        {intersede
          ? "Reunión entre las sedes: el acta sale sin el formato de ninguna. Queda guardada en esta sede."
          : `El acta sale con el formato de ${labels[sedes.findIndex((sede) => sede.id === activeOrg.id)]}.`}
      </p>
    </div>
  );
}
