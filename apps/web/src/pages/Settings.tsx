import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, NavLink, Navigate, Route, Routes, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { DriveStatusOut, MyDriveOut, ReasonOut } from "../api/types";
import { Select } from "../components/Select";
import { Switch } from "../components/Toggles";
import { Badge, Button, Card, Input, Modal, Spinner } from "../components/ui";
import { useAuth } from "../state/auth";
import { LEVEL_LABEL, useMyAccess, type Level, type LevelAccess } from "../state/access";
import { ACTA_ENTREVISTA_COLEGIO } from "../lib/actaTemplates";
import { LetterheadSection } from "./settings/LetterheadSection";
import { CreateOrJoin } from "./OnboardingOrg";
import { micErrorMessage } from "../lib/micError";

const SECTIONS = [
  { path: "org", label: "Organización" },
  { path: "ai", label: "Idioma del acta" },
  { path: "reasons", label: "Motivos de reunión" },
  { path: "dictionary", label: "Diccionario" },
  { path: "template", label: "Formato de acta" },
  { path: "numbering", label: "Numeración de actas" },
  { path: "letterhead", label: "Membrete" },
  { path: "drive", label: "Drive de la sede" },
  { path: "my-drive", label: "Mi Google Drive" },
  { path: "my-voice", label: "Mi voz" },
  { path: "devices", label: "Dispositivos" },
  { path: "notifications", label: "Notificaciones" },
  { path: "privacy", label: "Privacidad" },
];

export default function Settings() {
  const { data: myAccess } = useMyAccess();
  // "Niveles y accesos" solo para quien dirige algún nivel o es admin.
  const canManageAccess = (myAccess?.managed_levels.length ?? 0) > 0;
  const sections = canManageAccess
    ? [SECTIONS[0], { path: "access", label: "Niveles y accesos" }, ...SECTIONS.slice(1)]
    : SECTIONS;
  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight text-ink-900">Ajustes</h1>
      <div className="flex flex-col gap-8 md:flex-row">
        <nav className="flex shrink-0 flex-row gap-1 overflow-x-auto md:w-44 md:flex-col">
          {sections.map((section) => (
            <NavLink
              key={section.path}
              to={section.path}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium ${
                  isActive ? "bg-ink-100 text-ink-900" : "text-ink-500 hover:bg-ink-50"
                }`
              }
            >
              {section.label}
            </NavLink>
          ))}
        </nav>
        <div className="min-w-0 flex-1">
          <Routes>
            <Route index element={<Navigate to="org" replace />} />
            <Route path="org" element={<OrgSection />} />
            <Route path="access" element={<AccessSection />} />
            <Route path="ai" element={<AISection />} />
            <Route path="reasons" element={<ReasonsSection />} />
            <Route path="dictionary" element={<DictionarySection />} />
            <Route path="template" element={<TemplateSection />} />
            <Route path="numbering" element={<NumberingSection />} />
            <Route path="letterhead" element={<LetterheadSection />} />
            <Route path="drive" element={<DriveSection />} />
            <Route path="my-drive" element={<MyDriveSection />} />
            <Route path="my-voice" element={<MyVoiceSection />} />
            <Route path="devices" element={<DevicesSection />} />
            <Route path="notifications" element={<NotificationsSection />} />
            <Route path="privacy" element={<PrivacySection />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}

// ── Organización y miembros ──────────────────────────────────────

/** Desde la cuenta individual: sumarse al colegio con un código, o dar de alta la institución. */
function JoinOrCreateCard() {
  const [mode, setMode] = useState<"create" | "join">("join");
  return (
    <div>
      <h2 className="mb-1 font-semibold text-ink-900">¿Tu colegio usa Echo?</h2>
      <p className="mb-4 text-sm text-ink-500">
        Unite con el código de invitación que te pasen, o creá la organización de tu institución. Tu cuenta individual
        sigue estando: cambiás entre las dos desde el menú.
      </p>
      <CreateOrJoin mode={mode} onMode={setMode} />
    </div>
  );
}

function OrgSection() {
  const { activeOrg } = useAuth();
  const queryClient = useQueryClient();
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [lastInviteToken, setLastInviteToken] = useState<string | null>(null);

  const { data: members } = useQuery({
    queryKey: ["members", activeOrg?.id],
    queryFn: () =>
      api<{ id: string; user_id: string; name: string; email: string; role: string }[]>("/api/org/members"),
  });

  const invite = useMutation({
    mutationFn: () =>
      api<{ token: string }>("/api/org/invites", {
        method: "POST",
        body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
      }),
    onSuccess: (data) => {
      setLastInviteToken(data.token);
      setInviteEmail("");
    },
  });

  return (
    <div className="space-y-5">
      <Card>
        <h2 className="mb-1 font-semibold text-ink-900">{activeOrg?.name}</h2>
        <p className="text-sm text-ink-400">
          {activeOrg?.is_personal ? "Tu cuenta individual" : `Tu rol: ${activeOrg?.role}`}
        </p>
      </Card>

      {activeOrg?.is_personal && <JoinOrCreateCard />}

      <Card>
        <h2 className="mb-3 font-semibold text-ink-900">Miembros</h2>
        <ul className="mb-4 divide-y divide-ink-100">
          {members?.map((member) => (
            <li key={member.id} className="flex items-center justify-between py-2.5">
              <div>
                <p className="text-sm font-medium text-ink-800">{member.name}</p>
                <p className="text-xs text-ink-400">{member.email}</p>
              </div>
              <Badge tone={member.role === "owner" ? "indigo" : "gray"}>{member.role}</Badge>
            </li>
          ))}
        </ul>

        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            invite.mutate();
          }}
          className="flex flex-wrap items-end gap-2"
        >
          <div className="min-w-52 flex-1">
            <Input
              label="Invitar por email"
              type="email"
              placeholder="persona@empresa.com"
              value={inviteEmail}
              onChange={(event) => setInviteEmail(event.target.value)}
              required
            />
          </div>
          <Select
            ariaLabel="Rol"
            value={inviteRole}
            onChange={setInviteRole}
            options={[
              { value: "member", label: "Member" },
              { value: "admin", label: "Admin" },
              { value: "viewer", label: "Viewer" },
            ]}
            className="w-32 shrink-0"
          />
          <Button type="submit" disabled={invite.isPending}>
            {invite.isPending ? <Spinner /> : "Invitar"}
          </Button>
        </form>
        {invite.isError && (
          <p className="mt-2 text-sm text-red-600">
            {invite.error instanceof Error ? invite.error.message : "Error"}
          </p>
        )}
        {lastInviteToken && (
          <div className="mt-3 rounded-lg bg-ink-50 p-3 text-sm">
            <p className="mb-1 font-medium text-ink-700">Invitación creada. Compartí este código:</p>
            <code className="break-all text-xs text-ink-600">{lastInviteToken}</code>
            <p className="mt-1 text-xs text-ink-400">
              La persona lo ingresa al registrarse en «Tengo una invitación». Expira en 7 días.
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}

// ── Idioma del acta ──────────────────────────────────────────────
// Los colegios no eligen modelo ni cargan keys: las pone Becode.

function AISection() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({
    queryKey: ["ai-settings"],
    queryFn: () => api<{ minutes_language: string }>("/api/org/ai-settings"),
  });
  const save = useMutation({
    mutationFn: (minutes_language: string) =>
      api("/api/org/ai-settings", { method: "PUT", body: JSON.stringify({ minutes_language }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-settings"] }),
  });

  if (!settings) return <div className="flex justify-center py-10 text-ink-300"><Spinner /></div>;

  return (
    <Card>
      <h2 className="mb-1 font-semibold text-ink-900">Idioma del acta</h2>
      <p className="mb-4 text-sm text-ink-400">Puede ser distinto del idioma que se habló en la reunión.</p>
      <div className="flex items-center gap-3">
        <Select
          ariaLabel="Idioma del acta"
          value={settings.minutes_language}
          onChange={(value) => save.mutate(value)}
          options={[
            { value: "es", label: "Español" },
            { value: "en", label: "English" },
            { value: "pt", label: "Português" },
          ]}
          className="w-48"
        />
        {save.isPending && <Spinner />}
        {save.isSuccess && <span className="text-sm text-emerald-600">Guardado ✓</span>}
        {save.isError && (
          <span className="text-sm text-red-600">
            {save.error instanceof Error ? save.error.message : "No se pudo guardar"}
          </span>
        )}
      </div>
    </Card>
  );
}

// ── Diccionario ──────────────────────────────────────────────────

function DictionarySection() {
  const queryClient = useQueryClient();
  const [term, setTerm] = useState("");
  const [kind, setKind] = useState("term");

  const { data: entries } = useQuery({
    queryKey: ["dictionary"],
    queryFn: () => api<{ id: string; term: string; kind: string }[]>("/api/org/dictionary"),
  });

  const add = useMutation({
    mutationFn: () =>
      api("/api/org/dictionary", { method: "POST", body: JSON.stringify({ term, kind }) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dictionary"] });
      setTerm("");
    },
  });

  const remove = useMutation({
    mutationFn: (entryId: string) => api(`/api/org/dictionary/${entryId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dictionary"] }),
  });

  return (
    <Card>
      <h2 className="mb-1 font-semibold text-ink-900">Diccionario personalizado</h2>
      <p className="mb-4 text-sm text-ink-400">
        Nombres propios, productos y siglas de tu organización. Se usan como vocabulary bias del motor de
        transcripción y como contexto del modelo de IA.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (term.trim()) add.mutate();
        }}
        className="mb-4 flex flex-wrap gap-2"
      >
        <input
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder="ej: DOE, Testra, Typely"
          className="min-w-[180px] flex-1 rounded-lg border border-ink-200 px-3 py-2 text-sm focus:border-accent-500 focus:outline-none"
        />
        <Select
          ariaLabel="Tipo"
          value={kind}
          onChange={setKind}
          options={[
            { value: "term", label: "Término" },
            { value: "person", label: "Persona" },
            { value: "product", label: "Producto" },
            { value: "acronym", label: "Sigla" },
            { value: "vendor", label: "Proveedor" },
          ]}
          className="w-36 shrink-0"
        />
        <Button type="submit" disabled={add.isPending}>Agregar</Button>
      </form>
      <div className="flex flex-wrap gap-2">
        {entries?.map((entry) => (
          <span key={entry.id} className="inline-flex items-center gap-1.5 rounded-full bg-ink-100 px-3 py-1 text-sm text-ink-700">
            {entry.term}
            <button onClick={() => remove.mutate(entry.id)} className="text-ink-400 hover:text-red-600" aria-label={`Eliminar ${entry.term}`}>
              ×
            </button>
          </span>
        ))}
        {entries?.length === 0 && <p className="text-sm text-ink-400">Sin términos todavía.</p>}
      </div>
    </Card>
  );
}

// ── Plantilla de acta ────────────────────────────────────────────

function TemplateSection() {
  const queryClient = useQueryClient();
  const { data: template } = useQuery({
    queryKey: ["minutes-template"],
    queryFn: () =>
      api<{ id: string; name: string; body_markdown: string; is_provisional: boolean }>(
        "/api/org/minutes-template",
      ),
  });
  const [name, setName] = useState("");
  const [body, setBody] = useState("");

  useEffect(() => {
    if (template) {
      setName(template.name);
      setBody(template.body_markdown);
    }
  }, [template]);

  const save = useMutation({
    mutationFn: () =>
      api("/api/org/minutes-template", {
        method: "PUT",
        body: JSON.stringify({ name, body_markdown: body }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["minutes-template"] }),
  });

  if (!template) return <div className="flex justify-center py-10 text-ink-300"><Spinner /></div>;

  return (
    <Card>
      <div className="mb-3 flex items-center gap-2">
        <h2 className="font-semibold text-ink-900">Formato de acta</h2>
        {template.is_provisional && <Badge tone="amber">Plantilla provisional</Badge>}
      </div>
      <p className="mb-4 text-sm text-ink-400">
        Este modelo es la <strong>source of truth</strong> del generador de actas: pegá acá el modelo real
        de tu organización (estructura, títulos, tablas, firmas) y Echo lo respetará al pie de la letra.
      </p>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Button
          variant="soft"
          onClick={() => {
            setName("Acta de entrevista");
            setBody(ACTA_ENTREVISTA_COLEGIO);
          }}
        >
          Cargar modelo: acta de entrevista (colegio)
        </Button>
        <span className="text-xs text-ink-400">
          Alumno, curso, solicitada por, motivo, desarrollo, acuerdos y firmas. Ajustalo y guardalo.
        </span>
      </div>
      <div className="space-y-3">
        <Input label="Nombre de la plantilla" value={name} onChange={(event) => setName(event.target.value)} />
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={20}
          className="w-full rounded-lg border border-ink-200 p-4 font-mono text-sm leading-relaxed focus:border-accent-500 focus:outline-none"
        />
        <div className="flex items-center gap-3">
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? <Spinner /> : "Guardar como modelo oficial"}
          </Button>
          {save.isSuccess && <span className="text-sm text-emerald-600">Guardado ✓</span>}
        </div>
      </div>
    </Card>
  );
}

// ── Dispositivos ─────────────────────────────────────────────────

function DevicesSection() {
  const queryClient = useQueryClient();
  const [showClaim, setShowClaim] = useState(false);
  const [code, setCode] = useState("");
  const [deviceName, setDeviceName] = useState("Echo Device");

  const { data: devices } = useQuery({
    queryKey: ["devices"],
    queryFn: () =>
      api<{
        id: string;
        name: string;
        kind: string;
        firmware_version: string | null;
        last_seen_at: string | null;
        online: boolean;
        state: { wifi_rssi?: number } | null;
        minors: boolean;
      }[]>("/api/devices"),
    refetchInterval: 15_000,
  });

  const claim = useMutation({
    mutationFn: () =>
      api("/api/devices/claim", { method: "POST", body: JSON.stringify({ code, name: deviceName }) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["devices"] });
      setShowClaim(false);
      setCode("");
    },
  });

  const unlink = useMutation({
    mutationFn: (deviceId: string) => api(`/api/devices/${deviceId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["devices"] }),
  });

  const setMinors = useMutation({
    mutationFn: ({ deviceId, minors }: { deviceId: string; minors: boolean }) =>
      api(`/api/devices/${deviceId}`, { method: "PATCH", body: JSON.stringify({ minors }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["devices"] }),
  });

  return (
    <div className="space-y-5">
      <Card>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold text-ink-900">Echo Devices</h2>
          <Button variant="soft" onClick={() => setShowClaim(true)}>Vincular dispositivo</Button>
        </div>
        {devices?.length === 0 && (
          <p className="text-sm text-ink-400">
            Sin dispositivos. El Echo Device (ESP32) muestra un código en su pantalla al encenderse: usalo
            acá para vincularlo a la organización.
          </p>
        )}
        <ul className="divide-y divide-ink-100">
          {devices?.map((device) => (
            <li key={device.id} className="space-y-3 py-3">
              <div className="flex items-center justify-between">
              <div>
                <p className="flex items-center gap-2 text-sm font-medium text-ink-800">
                  <span className={`h-2 w-2 rounded-full ${device.online ? "bg-emerald-500" : "bg-ink-300"}`} />
                  {device.name}
                </p>
                <p className="text-xs text-ink-400">
                  {device.kind}
                  {device.firmware_version && ` · firmware ${device.firmware_version}`}
                  {device.state?.wifi_rssi != null && ` · WiFi ${device.state.wifi_rssi} dBm`}
                  {device.last_seen_at &&
                    ` · visto ${Math.max(0, Math.round((Date.now() - new Date(device.last_seen_at).getTime()) / 1000))} s atrás`}
                </p>
              </div>
              <Button variant="ghost" onClick={() => unlink.mutate(device.id)}>Desvincular</Button>
              </div>
              <Switch
                checked={device.minors}
                onChange={(minors) => setMinors.mutate({ deviceId: device.id, minors })}
                label="Pueden hablar menores de 18"
                hint={
                  device.minors
                    ? "Sus reuniones se transcriben sin separar quién habló y no las usa la voz de Echo."
                    : "Solo si nunca graba en un aula. Apagarlo lo puede hacer un admin."
                }
              />
            </li>
          ))}
        </ul>
        {setMinors.isError && (
          <p className="mt-2 text-sm text-red-600">
            {setMinors.error instanceof Error ? setMinors.error.message : "No se pudo cambiar"}
          </p>
        )}
      </Card>

      <Modal open={showClaim} onClose={() => setShowClaim(false)} title="Vincular dispositivo">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            claim.mutate();
          }}
          className="space-y-4"
        >
          <Input
            label="Código que muestra el dispositivo"
            placeholder="483921"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            autoFocus
            required
          />
          <Input label="Nombre" value={deviceName} onChange={(event) => setDeviceName(event.target.value)} />
          {claim.isError && (
            <p className="text-sm text-red-600">
              {claim.error instanceof Error ? claim.error.message : "Error"}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setShowClaim(false)}>Cancelar</Button>
            <Button type="submit" disabled={claim.isPending}>
              {claim.isPending ? <Spinner /> : "Vincular"}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

// ── Notificaciones ───────────────────────────────────────────────

function NotificationsSection() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ["notifications-full"],
    queryFn: () =>
      api<{ notifications: { id: string; title: string; body: string | null; link: string | null; read: boolean; created_at: string }[] }>(
        "/api/notifications",
      ),
  });
  const markAll = useMutation({
    mutationFn: () => api("/api/notifications/read-all", { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications-full"] });
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  return (
    <Card>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-semibold text-ink-900">Notificaciones</h2>
        <Button variant="soft" onClick={() => markAll.mutate()}>Marcar todo leído</Button>
      </div>
      <ul className="divide-y divide-ink-100">
        {data?.notifications.length === 0 && <p className="py-4 text-sm text-ink-400">Sin notificaciones.</p>}
        {data?.notifications.map((notification) => (
          <li key={notification.id} className={`py-3 ${notification.read ? "opacity-60" : ""}`}>
            <p className="text-sm font-medium text-ink-800">{notification.title}</p>
            {notification.body && <p className="text-sm text-ink-500">{notification.body}</p>}
            <p className="mt-0.5 text-xs text-ink-400">
              {new Date(notification.created_at).toLocaleString("es")}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  );
}

// ── Privacidad ───────────────────────────────────────────────────

function PrivacySection() {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const { data: deletion } = useQuery({
    queryKey: ["deletion-request"],
    queryFn: () => api<{ requested_at: string | null }>("/api/me/deletion-request", { skipOrg: true }),
  });
  const ask = useMutation({
    mutationFn: () => api("/api/me/deletion-request", { method: "POST", skipOrg: true }),
    onSuccess: () => {
      setConfirming(false);
      return queryClient.invalidateQueries({ queryKey: ["deletion-request"] });
    },
  });

  return (
    <div className="space-y-5">
      <Card>
        <h2 className="mb-3 font-semibold text-ink-900">Cómo cuida Echo tus datos</h2>
        <ul className="space-y-2.5 text-sm leading-relaxed text-ink-600">
          <li>
            <strong className="text-ink-800">El audio no queda guardado.</strong> Echo usa una copia de trabajo para
            transcribir y la borra al terminar (si algo falla, como mucho 48 horas). Solo si elegís grabar una reunión,
            el audio va a tu Google Drive.
          </li>
          <li>
            <strong className="text-ink-800">Los nombres no le llegan a la IA:</strong> se reemplazan por marcadores
            antes de redactar el acta o responder, y vuelven al terminar.
          </li>
          <li>
            <strong className="text-ink-800">Reuniones con menores:</strong> no se separa quién habló y la voz de Echo
            no las usa.
          </li>
          <li>
            <strong className="text-ink-800">Siempre se ve cuándo se graba:</strong> la app y el Echo Device muestran
            «● Grabando». Avisá a quienes participan que la reunión se transcribe.
          </li>
        </ul>
        <p className="mt-4 text-sm">
          <Link to="/legal/privacidad" className="font-medium text-ink-900 underline underline-offset-2">
            Leer la política de privacidad completa
          </Link>
        </p>
      </Card>

      <Card>
        <h2 className="mb-1 font-semibold text-ink-900">Tus datos</h2>
        <p className="mb-4 text-sm text-ink-500">
          Podés pedir una copia de tus datos, corregirlos o borrarlos (Ley 25.326).
        </p>
        <div className="flex flex-wrap gap-2">
          <Link
            to="/contacto?tema=privacidad"
            className="inline-flex min-h-11 items-center rounded-full bg-ink-100 px-4 text-sm font-medium text-ink-800 hover:bg-ink-200"
          >
            Pedir mis datos o corregirlos
          </Link>
          {!deletion?.requested_at && !confirming && (
            <button
              onClick={() => setConfirming(true)}
              className="min-h-11 rounded-full px-4 text-sm font-medium text-red-600 hover:bg-red-50"
            >
              Pedir la baja de mi cuenta
            </button>
          )}
        </div>
        {confirming && (
          <div className="mt-4 rounded-2xl bg-red-50 p-4 text-sm text-red-900">
            <p className="font-medium">¿Pedir la baja de tu cuenta?</p>
            <p className="mt-1 text-red-800">
              Becode borra tu cuenta y tus datos personales dentro de los 5 días hábiles. Las reuniones que hiciste para
              una institución quedan en la institución. No se puede deshacer.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                onClick={() => ask.mutate()}
                disabled={ask.isPending}
                className="min-h-11 rounded-full bg-red-600 px-4 font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {ask.isPending ? <Spinner /> : "Sí, pedir la baja"}
              </button>
              <button onClick={() => setConfirming(false)} className="min-h-11 rounded-full px-4 font-medium text-red-800">
                Cancelar
              </button>
            </div>
          </div>
        )}
        {deletion?.requested_at && (
          <p className="mt-4 rounded-2xl bg-ink-50 px-4 py-3 text-sm text-ink-600">
            Pediste la baja el {new Date(deletion.requested_at).toLocaleDateString("es-AR")}. Becode la procesa dentro de
            los 5 días hábiles y te avisa por mail.
          </p>
        )}
        {ask.isError && (
          <p className="mt-3 text-sm text-red-600">{ask.error instanceof Error ? ask.error.message : "No se pudo pedir"}</p>
        )}
      </Card>
    </div>
  );
}


// ── Motivos de reunión ───────────────────────────────────────────

function ReasonsSection() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");

  const { data: reasons, isLoading } = useQuery({
    queryKey: ["reasons", "all"],
    queryFn: () => api<ReasonOut[]>("/api/org/meeting-reasons?include_inactive=true"),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["reasons"] });
    queryClient.invalidateQueries({ queryKey: ["reasons", "all"] });
  };

  const create = useMutation({
    mutationFn: () =>
      api<ReasonOut>("/api/org/meeting-reasons", {
        method: "POST",
        body: JSON.stringify({ name, is_active: true, position: (reasons?.length ?? 0) + 1 }),
      }),
    onSuccess: () => {
      setName("");
      invalidate();
    },
  });

  const toggle = useMutation({
    mutationFn: (reason: ReasonOut) =>
      api<ReasonOut>(`/api/org/meeting-reasons/${reason.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: reason.name,
          is_active: !reason.is_active,
          position: reason.position,
        }),
      }),
    onSuccess: invalidate,
  });

  if (isLoading) {
    return <div className="flex justify-center py-10 text-ink-300"><Spinner className="h-5 w-5" /></div>;
  }

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-[15px] font-semibold text-ink-900">Motivos de reunión</h2>
        <p className="mt-1 text-sm text-ink-500">
          La lista que aparece al clasificar una reunión. Tenerla cerrada es lo que hace que los
          reportes por motivo sirvan para algo.
        </p>
      </div>

      {(reasons ?? []).length > 0 && (
        <ul className="space-y-1.5">
          {(reasons ?? []).map((reason) => (
            <li key={reason.id} className="flex items-center gap-2 text-sm">
              <span className={reason.is_active ? "text-ink-800" : "text-ink-400 line-through"}>
                {reason.name}
              </span>
              {!reason.is_active && <Badge tone="gray">Inactivo</Badge>}
              <button
                onClick={() => toggle.mutate(reason)}
                className="ml-auto text-xs text-ink-400 hover:text-ink-700"
              >
                {reason.is_active ? "Desactivar" : "Reactivar"}
              </button>
            </li>
          ))}
        </ul>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) create.mutate();
        }}
        className="flex flex-wrap items-end gap-2"
      >
        <div className="min-w-[200px] flex-1">
          <Input
            label="Nuevo motivo"
            placeholder="ej: Seguimiento pedagógico, Conducta, Inasistencias"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <Button type="submit" variant="soft" disabled={create.isPending}>
          {create.isPending ? <Spinner /> : "Agregar"}
        </Button>
      </form>
      {create.isError && (
        <p className="text-sm text-red-600">
          {create.error instanceof Error ? create.error.message : "No se pudo agregar"}
        </p>
      )}
      <p className="text-xs text-ink-400">
        Los motivos se desactivan en vez de borrarse: las reuniones viejas tienen que seguir
        mostrando con qué motivo se cargaron.
      </p>
    </Card>
  );
}

// ── Niveles y accesos ────────────────────────────────────────────

interface AccessMember {
  user_id: string;
  name: string;
  email: string;
  role: string;
  access: Partial<Record<Level, LevelAccess>>;
}

interface AccessList {
  managed_levels: Level[];
  can_assign_direction: boolean;
  members: AccessMember[];
}

const ACCESS_LABEL: Record<string, string> = {
  direccion: "Dirección",
  total: "Total",
  limitado: "Limitado",
  nulo: "Sin acceso",
};

function AccessSection() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [filter, setFilter] = useState("");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["level-access"],
    queryFn: () => api<AccessList>("/api/org/access"),
  });

  const setAccess = useMutation({
    mutationFn: (change: { user_id: string; level: Level; access: string }) =>
      api<AccessMember>("/api/org/access", { method: "PUT", body: JSON.stringify(change) }),
    onSuccess: (member) => {
      queryClient.setQueryData<AccessList>(["level-access"], (current) =>
        current
          ? { ...current, members: current.members.map((m) => (m.user_id === member.user_id ? member : m)) }
          : current,
      );
    },
  });

  if (isLoading) return <div className="flex justify-center py-10 text-ink-300"><Spinner className="h-5 w-5" /></div>;
  if (isError || !data) {
    return (
      <Card>
        <p className="text-sm text-ink-500">{error instanceof Error ? error.message : "No se pudieron cargar los accesos."}</p>
      </Card>
    );
  }

  const options = (["direccion", "total", "limitado", "nulo"] as const)
    .filter((value) => value !== "direccion" || data.can_assign_direction)
    .map((value) => ({ value, label: ACCESS_LABEL[value] }));
  const term = filter.trim().toLowerCase();
  const members = data.members.filter(
    (member) => !term || member.name.toLowerCase().includes(term) || member.email.toLowerCase().includes(term),
  );

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-[15px] font-semibold text-ink-900">Niveles y accesos</h2>
        <p className="mt-1 text-sm text-ink-500">
          Qué ve cada persona de {data.managed_levels.map((level) => LEVEL_LABEL[level]).join(", ")}.{" "}
          <span className="font-medium text-ink-700">Total</span>: todas las reuniones del nivel.{" "}
          <span className="font-medium text-ink-700">Limitado</span>: solo las suyas y las que le
          compartan. <span className="font-medium text-ink-700">Sin acceso</span>: nada del nivel.
          {data.can_assign_direction && (
            <>
              {" "}
              <span className="font-medium text-ink-700">Dirección</span>: todo el nivel, y asigna estos
              accesos.
            </>
          )}
        </p>
      </div>

      {data.members.length > 6 && (
        <Input placeholder="Buscar persona…" value={filter} onChange={(event) => setFilter(event.target.value)} />
      )}

      <ul className="divide-y divide-ink-100">
        {members.map((member) => {
          const admin = member.role === "admin" || member.role === "owner";
          return (
            <li key={member.user_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
              <div className="min-w-0 flex-1 basis-48">
                <p className="truncate text-sm font-medium text-ink-900">
                  {member.name}
                  {member.user_id === user?.id && <span className="font-normal text-ink-400"> (vos)</span>}
                </p>
                <p className="truncate text-xs text-ink-400">{member.email}</p>
              </div>
              {admin ? (
                <Badge tone="indigo">Admin de la sede: ve todo</Badge>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {data.managed_levels.map((level) => {
                    const current = member.access[level] ?? "nulo";
                    // Dirección no se toca a sí misma ni a otra dirección: eso es de un admin.
                    const locked =
                      !data.can_assign_direction && (current === "direccion" || member.user_id === user?.id);
                    return (
                      <div key={level} className="w-36">
                        <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-ink-400">
                          {LEVEL_LABEL[level]}
                        </span>
                        {locked ? (
                          <p className="py-1 text-xs font-medium text-ink-700">{ACCESS_LABEL[current]}</p>
                        ) : (
                          <Select
                            size="sm"
                            ariaLabel={`Acceso de ${member.name} a ${LEVEL_LABEL[level]}`}
                            value={current}
                            onChange={(access) =>
                              access !== current && setAccess.mutate({ user_id: member.user_id, level, access })
                            }
                            options={options}
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </li>
          );
        })}
        {members.length === 0 && <li className="py-6 text-center text-sm text-ink-400">Nadie coincide.</li>}
      </ul>
      {setAccess.isError && (
        <p className="text-sm text-red-600">
          {setAccess.error instanceof Error ? setAccess.error.message : "No se pudo cambiar el acceso"}
        </p>
      )}
    </Card>
  );
}

// ── Numeración de actas ──────────────────────────────────────────

interface NumberingOut {
  next_number: number;
  last_assigned: number | null;
}

function NumberingSection() {
  const queryClient = useQueryClient();
  const { activeOrg } = useAuth();
  const isAdmin = activeOrg?.role === "owner" || activeOrg?.role === "admin";
  const [value, setValue] = useState("");

  const { data: numbering, isLoading } = useQuery({
    queryKey: ["minutes-numbering"],
    queryFn: () => api<NumberingOut>("/api/org/minutes-numbering"),
  });

  const save = useMutation({
    mutationFn: (nextNumber: number) =>
      api<NumberingOut>("/api/org/minutes-numbering", {
        method: "PUT",
        body: JSON.stringify({ next_number: nextNumber }),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["minutes-numbering"], data);
      setValue("");
    },
  });

  if (isLoading || !numbering) {
    return <div className="flex justify-center py-10 text-ink-300"><Spinner className="h-5 w-5" /></div>;
  }

  const minimum = (numbering.last_assigned ?? 0) + 1;
  const parsed = Number(value);
  const valid = value.trim() !== "" && Number.isInteger(parsed) && parsed >= minimum;

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-[15px] font-semibold text-ink-900">Numeración de actas</h2>
        <p className="mt-1 text-sm text-ink-500">
          Cada acta recibe un número correlativo de esta sede cuando se genera o se imprime por
          primera vez, lo que pase antes. Una vez asignado no cambia, y dos actas nunca comparten
          número, aunque se impriman al mismo tiempo desde reuniones distintas.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:max-w-md">
        <div className="rounded-lg bg-ink-50 px-4 py-3">
          <p className="text-xs text-ink-500">Última asignada</p>
          <p className="text-xl font-semibold tabular-nums text-ink-900">
            {numbering.last_assigned != null ? `N.º ${numbering.last_assigned}` : "—"}
          </p>
        </div>
        <div className="rounded-lg bg-ink-50 px-4 py-3">
          <p className="text-xs text-ink-500">Próxima</p>
          <p className="text-xl font-semibold tabular-nums text-ink-900">N.º {numbering.next_number}</p>
        </div>
      </div>

      {isAdmin ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (valid) save.mutate(parsed);
          }}
          className="space-y-2"
        >
          <div className="flex flex-wrap items-end gap-2">
            <div className="w-44">
              <Input
                label="Seguir desde el número"
                type="number"
                inputMode="numeric"
                min={minimum}
                step={1}
                placeholder={String(numbering.next_number)}
                value={value}
                onChange={(event) => setValue(event.target.value)}
              />
            </div>
            <Button type="submit" variant="soft" disabled={!valid || save.isPending}>
              {save.isPending ? <Spinner /> : "Guardar"}
            </Button>
          </div>
          <p className="text-xs text-ink-400">
            Sirve para continuar la numeración que traían de antes: si el último acta en papel fue la
            N.º 347, poné 348.
            {numbering.last_assigned != null &&
              ` No puede ser menor a ${minimum}: hasta la ${minimum - 1} ya están usadas.`}
          </p>
          {value.trim() !== "" && !valid && (
            <p className="text-sm text-red-600">Tiene que ser un número entero desde {minimum}.</p>
          )}
          {save.isError && (
            <p className="text-sm text-red-600">
              {save.error instanceof Error ? save.error.message : "No se pudo guardar"}
            </p>
          )}
        </form>
      ) : (
        <p className="text-xs text-ink-400">Solo un administrador puede cambiar desde qué número sigue.</p>
      )}
    </Card>
  );
}

// ── Google Drive ─────────────────────────────────────────────────

const DRIVE_ERRORS: Record<string, string> = {
  cancelado: "Cancelaste la conexión con Google Drive.",
  estado: "La conexión tardó demasiado. Probá de nuevo.",
  permisos: "Necesitás ser administrador de la organización para conectar Drive.",
  google: "Google rechazó la conexión. Probá de nuevo en un momento.",
  sin_refresh:
    "Google no devolvió un permiso duradero. Quitá el acceso de Echo en tu cuenta de Google y volvé a conectar.",
};

function DriveSection() {
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();

  const { data: drive, isLoading } = useQuery({
    queryKey: ["drive-status"],
    queryFn: () => api<DriveStatusOut>("/api/org/drive/status"),
  });

  const connect = useMutation({
    mutationFn: () => api<{ url: string }>("/api/org/drive/connect-url", { method: "POST" }),
    onSuccess: (data) => {
      window.location.href = data.url;
    },
  });

  const disconnect = useMutation({
    mutationFn: () => api("/api/org/drive", { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["drive-status"] }),
  });

  const oauthError = DRIVE_ERRORS[params.get("error") ?? ""] ?? null;
  const justConnected = params.get("connected") === "1";

  if (isLoading) {
    return <div className="flex justify-center py-10 text-ink-300"><Spinner className="h-5 w-5" /></div>;
  }

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-[15px] font-semibold text-ink-900">Google Drive</h2>
        <p className="mt-1 text-sm text-ink-500">
          Al aprobar un acta, Echo la guarda sola en Drive: crea la carpeta de la familia si no
          existe y completa su enlace. Nadie tiene que subir nada a mano.
        </p>
      </div>

      {oauthError && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{oauthError}</p>
      )}
      {justConnected && drive?.connected && (
        <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          Drive conectado.
        </p>
      )}
      {drive?.last_error && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Última subida fallida: {drive.last_error}
        </p>
      )}

      {!drive?.enabled ? (
        <p className="text-sm text-ink-500">
          El servidor no tiene credenciales de Google configuradas, así que esta integración no
          está disponible.
        </p>
      ) : drive.connected ? (
        <div className="space-y-3">
          <p className="text-sm text-ink-700">
            Conectada con <span className="font-medium">{drive.connected_email}</span>.
          </p>
          {drive.root_folder_url && (
            <p className="text-sm text-ink-500">
              Carpeta madre:{" "}
              <a
                href={drive.root_folder_url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-accent-600 hover:underline"
              >
                abrir en Drive ↗
              </a>
              . Podés moverla a donde quieras dentro de tu Drive, incluso a una unidad compartida:
              el acceso no depende de dónde esté.
            </p>
          )}
          <div className="flex items-center gap-2">
            <Button
              variant="soft"
              onClick={() => {
                setParams({});
                disconnect.mutate();
              }}
              disabled={disconnect.isPending}
            >
              {disconnect.isPending ? <Spinner /> : "Desconectar"}
            </Button>
            <span className="text-xs text-ink-400">
              Desconectar borra el permiso, no los archivos: lo que ya está en Drive queda.
            </span>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <Button onClick={() => connect.mutate()} disabled={connect.isPending}>
            {connect.isPending ? <Spinner /> : "Conectar Google Drive"}
          </Button>
          {connect.isError && (
            <p className="text-sm text-red-600">
              {connect.error instanceof Error ? connect.error.message : "No se pudo iniciar"}
            </p>
          )}
          <p className="text-xs text-ink-400">
            Echo pide el permiso mínimo de Drive: solo puede ver y tocar lo que él mismo crea. No
            accede al resto de tus archivos.
          </p>
        </div>
      )}
    </Card>
  );
}

/**
 * Drive personal: adonde van las grabaciones que hace cada persona. Separado
 * del de la sede (donde van las actas): la grabación es de quien grabó.
 */
function MyDriveSection() {
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();

  const { data: drive, isLoading } = useQuery({
    queryKey: ["my-drive"],
    queryFn: () => api<MyDriveOut>("/api/me/drive", { skipOrg: true }),
  });
  const connect = useMutation({
    mutationFn: () => api<{ url: string }>("/api/me/drive/connect-url", { method: "POST", skipOrg: true }),
    onSuccess: (data) => {
      window.location.href = data.url;
    },
  });
  const disconnect = useMutation({
    mutationFn: () => api("/api/me/drive", { method: "DELETE", skipOrg: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["my-drive"] }),
  });

  const oauthError = DRIVE_ERRORS[params.get("error") ?? ""] ?? null;
  const justConnected = params.get("connected") === "1";

  if (isLoading) {
    return <div className="flex justify-center py-10 text-ink-300"><Spinner className="h-5 w-5" /></div>;
  }

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-[15px] font-semibold text-ink-900">Mi Google Drive</h2>
        <p className="mt-1 text-sm text-ink-500">
          Cuando grabás una reunión, al terminar Echo sube el audio a la carpeta «Echo — Grabaciones»
          de tu Drive y lo borra de sus servidores. Sin Drive conectado, el audio queda para
          descargar 48 horas y después se borra.
        </p>
      </div>

      {oauthError && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{oauthError}</p>}
      {justConnected && drive?.connected && (
        <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">Drive conectado.</p>
      )}
      {drive?.last_error && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Última subida fallida: {drive.last_error}
        </p>
      )}

      {!drive?.enabled ? (
        <p className="text-sm text-ink-500">
          El servidor no tiene credenciales de Google configuradas, así que esta integración no está
          disponible.
        </p>
      ) : drive.connected ? (
        <div className="space-y-3">
          <p className="text-sm text-ink-700">
            Conectado con <span className="font-medium">{drive.connected_email}</span>.
            {drive.folder_url && (
              <>
                {" "}
                <a
                  href={drive.folder_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-accent-600 hover:underline"
                >
                  Abrir la carpeta de grabaciones ↗
                </a>
              </>
            )}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="soft"
              onClick={() => {
                setParams({});
                disconnect.mutate();
              }}
              disabled={disconnect.isPending}
            >
              {disconnect.isPending ? <Spinner /> : "Desconectar"}
            </Button>
            <span className="text-xs text-ink-400">Tus grabaciones que ya están en Drive quedan ahí.</span>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <Button onClick={() => connect.mutate()} disabled={connect.isPending}>
            {connect.isPending ? <Spinner /> : "Conectar mi Google Drive"}
          </Button>
          {connect.isError && (
            <p className="text-sm text-red-600">
              {connect.error instanceof Error ? connect.error.message : "No se pudo iniciar"}
            </p>
          )}
          <p className="text-xs text-ink-400">
            Permiso mínimo: Echo solo ve y toca los archivos que él mismo crea en tu Drive.
          </p>
        </div>
      )}
    </Card>
  );
}

interface VoiceOut {
  has_sample: boolean;
  duration_ms: number | null;
  recorded_at: string | null;
}

const VOICE_SECONDS = 10;

/**
 * Mi voz: una muestra corta para que, en las reuniones, el transcript diga el
 * nombre de la persona en vez de "Persona 2" (services/diarization.py).
 */
function MyVoiceSection() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [consent, setConsent] = useState(false);
  const [recording, setRecording] = useState(false);
  const [left, setLeft] = useState(VOICE_SECONDS);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);

  const { data: voice, isLoading } = useQuery({
    queryKey: ["my-voice"],
    queryFn: () => api<VoiceOut>("/api/me/voice", { skipOrg: true }),
  });
  const remove = useMutation({
    mutationFn: () => api("/api/me/voice", { method: "DELETE", skipOrg: true }),
    onSuccess: () => {
      setConfirmDelete(false);
      return queryClient.invalidateQueries({ queryKey: ["my-voice"] });
    },
  });

  useEffect(() => () => recorder.current?.stream.getTracks().forEach((track) => track.stop()), []);

  const upload = async (blob: Blob) => {
    setSaving(true);
    try {
      const form = new FormData();
      const extension = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
      form.append("audio", blob, `voz.${extension}`);
      form.append("consent", "true");
      await api<VoiceOut>("/api/me/voice", { method: "POST", body: form, skipOrg: true });
      await queryClient.invalidateQueries({ queryKey: ["my-voice"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar la muestra");
    } finally {
      setSaving(false);
    }
  };

  const start = async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      const chunks: Blob[] = [];
      const media = new MediaRecorder(stream);
      recorder.current = media;
      media.ondataavailable = (event) => event.data.size && chunks.push(event.data);
      media.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        setRecording(false);
        void upload(new Blob(chunks, { type: media.mimeType || "audio/webm" }));
      };
      media.start();
      setRecording(true);
      setLeft(VOICE_SECONDS);
      const started = Date.now();
      const tick = window.setInterval(() => {
        const remaining = VOICE_SECONDS - Math.floor((Date.now() - started) / 1000);
        setLeft(Math.max(0, remaining));
        if (remaining <= 0 || media.state !== "recording") {
          window.clearInterval(tick);
          if (media.state === "recording") media.stop();
        }
      }, 250);
    } catch (err) {
      setError(micErrorMessage(err));
    }
  };

  if (isLoading) {
    return <div className="flex justify-center py-10 text-ink-300"><Spinner className="h-5 w-5" /></div>;
  }

  const firstName = (user?.name ?? "").split(" ")[0] || "…";

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-[15px] font-semibold text-ink-900">Mi voz</h2>
        <p className="mt-1 text-sm text-ink-500">
          Grabá tu voz una vez, durante 10 segundos, y Echo te va a reconocer en las reuniones: en el
          transcript y en el acta aparece tu nombre en lugar de «Persona 1».
        </p>
      </div>

      {voice?.has_sample && !recording && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg bg-emerald-50 px-3 py-2.5 text-sm text-emerald-800">
          <span className="min-w-0 flex-1">
            Tu voz está guardada
            {voice.recorded_at && ` desde el ${new Date(voice.recorded_at).toLocaleDateString("es")}`}.
          </span>
          {confirmDelete ? (
            <span className="flex items-center gap-2 text-xs">
              <span className="text-ink-600">¿Borrar tu voz? Echo deja de reconocerte.</span>
              <button
                onClick={() => remove.mutate()}
                disabled={remove.isPending}
                className="rounded-full bg-red-600 px-3 py-1.5 font-medium text-white hover:bg-red-700"
              >
                Sí, borrar
              </button>
              <button onClick={() => setConfirmDelete(false)} className="px-2 py-1.5 font-medium text-ink-500">
                Cancelar
              </button>
            </span>
          ) : (
            <button
              onClick={() => setConfirmDelete(true)}
              className="text-xs font-medium text-emerald-700 hover:text-red-600"
            >
              Borrar mi voz
            </button>
          )}
        </div>
      )}

      <div className="space-y-3 rounded-xl border border-ink-100 p-4">
        <p className="text-sm text-ink-600">Cuando toques grabar, leé en voz alta, con tu tono normal:</p>
        <blockquote className="rounded-lg bg-ink-50 px-3 py-2.5 text-[15px] leading-relaxed text-ink-800">
          «Hola, soy {firstName}. Estoy grabando mi voz para que Echo me reconozca en las reuniones del
          colegio. Después de cada reunión, el resumen va a decir quién dijo cada cosa.»
        </blockquote>
        <label className="flex items-start gap-2 text-sm text-ink-600">
          <input
            type="checkbox"
            checked={consent}
            onChange={(event) => setConsent(event.target.checked)}
            className="mt-0.5 rounded border-ink-300"
          />
          <span>
            Autorizo a Echo a guardar esta muestra de mi voz y a usarla solo para reconocerme en las
            reuniones. La puedo borrar cuando quiera.
          </span>
        </label>
        <div className="flex flex-wrap items-center gap-3">
          {recording ? (
            <Button variant="danger" onClick={() => recorder.current?.stop()}>
              <span className="recording-dot h-2 w-2 rounded-full bg-white" /> Grabando… {left} s · Listo
            </Button>
          ) : (
            <Button onClick={start} disabled={!consent || saving}>
              {saving ? <Spinner /> : voice?.has_sample ? "Grabar de nuevo" : "Grabar mi voz"}
            </Button>
          )}
          {!consent && !recording && (
            <span className="text-xs text-ink-400">Marcá la autorización para poder grabar.</span>
          )}
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>
    </Card>
  );
}
