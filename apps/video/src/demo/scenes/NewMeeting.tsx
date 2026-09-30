import { Button } from "../../../../web/src/components/ui";
import { pressScale } from "../anim";
import { MODAL_COMENZAR } from "../layout";
import { CLICK } from "../timeline";

/** El modal real "Nueva reunión" (pages/Meetings.tsx), 512×536. */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink-700">{label}</span>
      {children}
    </label>
  );
}

function SelectBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex w-full items-center gap-2 rounded-lg border border-ink-200 bg-white px-3 py-2 text-left text-sm">
      <span className="min-w-0 flex-1 truncate text-ink-900">{children}</span>
      <svg width={14} height={14} viewBox="0 0 16 16" fill="none" className="shrink-0 text-ink-400">
        <path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

function TextBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900">{children}</div>
  );
}

export function NewMeeting({ frame }: { frame: number }) {
  return (
    <div className="h-full w-full bg-white p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-ink-900">Nueva reunión</h2>
        <span className="rounded-lg p-1.5 text-ink-400">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </span>
      </div>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label="Familia">
            <SelectBox>
              Familia Romero <span className="text-ink-400">· 1482</span>
            </SelectBox>
          </Field>
          <Field label="¿Con quién es?">
            <SelectBox>Familia y profesionales</SelectBox>
          </Field>
        </div>
        <Field label="Nombre">
          <TextBox>Familia Romero · 28 sept</TextBox>
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Idioma">
            <SelectBox>Español</SelectBox>
          </Field>
          <Field label="Proyecto">
            <SelectBox>Sin proyecto</SelectBox>
          </Field>
        </div>
        <Field label="Participantes (separados por coma)">
          <TextBox>Directora, Orientadora (DOE), Mamá de Pedro</TextBox>
        </Field>
        <label className="flex items-center gap-2 text-sm text-ink-600">
          <span className="h-4 w-4 rounded border border-ink-300 bg-white" />
          Reunión privada (solo vos y con quien la compartas)
        </label>
        <label className="flex items-center gap-2 text-sm text-ink-600">
          <span className="h-4 w-4 rounded border border-ink-300 bg-white" />
          Grabar el audio completo
        </label>
      </div>
      <div
        className="absolute flex justify-end gap-2"
        style={{ right: 24, top: MODAL_COMENZAR.y - MODAL_COMENZAR.h / 2 }}
      >
        <Button variant="ghost">Cancelar</Button>
        <Button style={{ width: MODAL_COMENZAR.w, transform: `scale(${pressScale(frame, CLICK.comenzar)})` }}>
          Comenzar reunión
        </Button>
      </div>
    </div>
  );
}
