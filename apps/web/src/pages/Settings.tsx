import { useEffect, useState, type FormEvent } from "react";
import { NavLink, Navigate, Route, Routes, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { DriveStatusOut, ReasonOut } from "../api/types";
import { Badge, Button, Card, Input, Modal, Spinner } from "../components/ui";
import { useAuth } from "../state/auth";
import { ACTA_ENTREVISTA_COLEGIO } from "../lib/actaTemplates";
import { LetterheadSection } from "./settings/LetterheadSection";

const SECTIONS = [
  { path: "org", label: "Organización" },
  { path: "ai", label: "IA y transcripción" },
  { path: "reasons", label: "Motivos de reunión" },
  { path: "dictionary", label: "Diccionario" },
  { path: "template", label: "Formato de acta" },
  { path: "letterhead", label: "Membrete" },
  { path: "drive", label: "Google Drive" },
  { path: "devices", label: "Dispositivos" },
  { path: "notifications", label: "Notificaciones" },
  { path: "privacy", label: "Privacidad" },
];

export default function Settings() {
  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight text-ink-900">Ajustes</h1>
      <div className="flex flex-col gap-8 md:flex-row">
        <nav className="flex shrink-0 flex-row gap-1 overflow-x-auto md:w-44 md:flex-col">
          {SECTIONS.map((section) => (
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
            <Route path="ai" element={<AISection />} />
            <Route path="reasons" element={<ReasonsSection />} />
            <Route path="dictionary" element={<DictionarySection />} />
            <Route path="template" element={<TemplateSection />} />
            <Route path="letterhead" element={<LetterheadSection />} />
            <Route path="drive" element={<DriveSection />} />
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
        <p className="text-sm text-ink-400">Tu rol: {activeOrg?.role}</p>
      </Card>

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
          <select
            value={inviteRole}
            onChange={(event) => setInviteRole(event.target.value)}
            className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
          >
            <option value="member">Member</option>
            <option value="admin">Admin</option>
            <option value="viewer">Viewer</option>
          </select>
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

// ── IA / STT / Embeddings ────────────────────────────────────────

interface AISettings {
  llm_provider: string | null;
  llm_model: string | null;
  llm_api_key_masked: string | null;
  llm_base_url: string | null;
  llm_temperature: string | null;
  stt_provider: string | null;
  stt_model: string | null;
  stt_api_key_masked: string | null;
  embeddings_provider: string | null;
  embeddings_model: string | null;
  embeddings_api_key_masked: string | null;
  minutes_language: string;
  available: { llm_providers: string[]; stt_providers: string[]; embedding_providers: string[] };
  effective: {
    llm: { provider: string; model: string } | null;
    stt: { provider: string; model: string } | null;
    embeddings: { provider: string; model: string } | null;
  };
}

/** Qué está usando el servidor ahora mismo. "Default del servidor" sin esto
 *  es una caja negra: no se ve si el chat quedó en GMI o si hay STT activo. */
function ActiveBadge({ active }: { active: { provider: string; model: string } | null }) {
  if (!active) {
    return (
      <p className="mb-3 inline-flex rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700">
        Sin configurar — esta función no va a andar
      </p>
    );
  }
  return (
    <p className="mb-3 inline-flex rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
      Activo: {active.provider} · {active.model}
    </p>
  );
}

function AISection() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({
    queryKey: ["ai-settings"],
    queryFn: () => api<AISettings>("/api/org/ai-settings"),
  });

  const [form, setForm] = useState<Record<string, string>>({});
  useEffect(() => {
    if (settings) {
      setForm({
        llm_provider: settings.llm_provider ?? "",
        llm_model: settings.llm_model ?? "",
        llm_api_key: "",
        llm_temperature: settings.llm_temperature ?? "0.2",
        stt_provider: settings.stt_provider ?? "",
        stt_model: settings.stt_model ?? "",
        stt_api_key: "",
        embeddings_provider: settings.embeddings_provider ?? "",
        embeddings_api_key: "",
        minutes_language: settings.minutes_language ?? "es",
      });
    }
  }, [settings]);

  const save = useMutation({
    mutationFn: () =>
      api("/api/org/ai-settings", {
        method: "PUT",
        body: JSON.stringify({
          llm_provider: form.llm_provider || null,
          llm_model: form.llm_model || null,
          llm_api_key: form.llm_api_key === "" ? null : form.llm_api_key,
          llm_temperature: form.llm_temperature || null,
          stt_provider: form.stt_provider || null,
          stt_model: form.stt_model || null,
          stt_api_key: form.stt_api_key === "" ? null : form.stt_api_key,
          embeddings_provider: form.embeddings_provider || null,
          embeddings_api_key: form.embeddings_api_key === "" ? null : form.embeddings_api_key,
          minutes_language: form.minutes_language || null,
        }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-settings"] }),
  });

  const set = (key: string) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  if (!settings) return <div className="flex justify-center py-10 text-ink-300"><Spinner /></div>;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
      className="space-y-5"
    >
      <Card>
        <h2 className="mb-1 font-semibold text-ink-900">Modelo de IA (resúmenes, actas, chat)</h2>
        <ActiveBadge active={settings.effective.llm} />
        <p className="mb-4 text-sm text-ink-400">
          La API key se guarda cifrada y nunca vuelve completa al navegador.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700">Proveedor</span>
            <select value={form.llm_provider ?? ""} onChange={set("llm_provider")} className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm">
              <option value="">— usar default del servidor —</option>
              {settings.available.llm_providers.map((provider) => (
                <option key={provider} value={provider}>{provider}</option>
              ))}
            </select>
          </label>
          <Input label="Modelo" placeholder="ej: claude-sonnet-5, gpt-4o-mini" value={form.llm_model ?? ""} onChange={set("llm_model")} />
          <Input
            label={`API key ${settings.llm_api_key_masked ? `(actual: ${settings.llm_api_key_masked})` : ""}`}
            type="password"
            placeholder="Dejar vacío para no cambiar"
            value={form.llm_api_key ?? ""}
            onChange={set("llm_api_key")}
            autoComplete="off"
          />
          <Input label="Temperature" value={form.llm_temperature ?? ""} onChange={set("llm_temperature")} />
        </div>
      </Card>

      <Card>
        <h2 className="mb-1 font-semibold text-ink-900">Motor de transcripción (cloud fallback)</h2>
        <ActiveBadge active={settings.effective.stt} />
        <p className="mb-4 text-sm text-ink-400">
          El modo preferido es Echo Bridge (local, el audio no sale de tu máquina). El modo cloud envía
          temporalmente el audio al proveedor seleccionado y lo descarta al transcribir.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700">Proveedor</span>
            <select value={form.stt_provider ?? ""} onChange={set("stt_provider")} className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm">
              <option value="">— usar default del servidor —</option>
              {settings.available.stt_providers.map((provider) => (
                <option key={provider} value={provider}>{provider === "bridge" ? "bridge (solo local)" : provider}</option>
              ))}
            </select>
          </label>
          <Input
            label="Modelo"
            placeholder="whisper-1 · gpt-4o-transcribe-diarize (separa hablantes)"
            value={form.stt_model ?? ""}
            onChange={set("stt_model")}
          />
          <Input
            label={`API key ${settings.stt_api_key_masked ? `(actual: ${settings.stt_api_key_masked})` : ""}`}
            type="password"
            placeholder="Dejar vacío para no cambiar"
            value={form.stt_api_key ?? ""}
            onChange={set("stt_api_key")}
            autoComplete="off"
          />
        </div>
      </Card>

      <Card>
        <h2 className="mb-1 font-semibold text-ink-900">Embeddings (búsqueda semántica y RAG)</h2>
        <ActiveBadge active={settings.effective.embeddings} />
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700">Proveedor</span>
            <select value={form.embeddings_provider ?? ""} onChange={set("embeddings_provider")} className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm">
              <option value="">— usar default del servidor —</option>
              {settings.available.embedding_providers.map((provider) => (
                <option key={provider} value={provider}>{provider}</option>
              ))}
            </select>
          </label>
          <Input
            label={`API key ${settings.embeddings_api_key_masked ? `(actual: ${settings.embeddings_api_key_masked})` : ""}`}
            type="password"
            placeholder="Dejar vacío para no cambiar"
            value={form.embeddings_api_key ?? ""}
            onChange={set("embeddings_api_key")}
            autoComplete="off"
          />
        </div>
      </Card>

      <Card>
        <h2 className="mb-3 font-semibold text-ink-900">Idioma del acta</h2>
        <select value={form.minutes_language ?? "es"} onChange={set("minutes_language")} className="rounded-lg border border-ink-200 px-3 py-2 text-sm">
          <option value="es">Español</option>
          <option value="en">English</option>
          <option value="pt">Português</option>
        </select>
        <p className="mt-2 text-xs text-ink-400">Puede diferir del idioma hablado en la reunión.</p>
      </Card>

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? <Spinner /> : "Guardar"}
        </Button>
        {save.isSuccess && <span className="text-sm text-emerald-600">Guardado ✓</span>}
        {save.isError && (
          <span className="text-sm text-red-600">
            {save.error instanceof Error ? save.error.message : "Error"}
          </span>
        )}
      </div>
    </form>
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
        className="mb-4 flex gap-2"
      >
        <input
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder="ej: DOE, Testra, Typely"
          className="flex-1 rounded-lg border border-ink-200 px-3 py-2 text-sm focus:border-accent-500 focus:outline-none"
        />
        <select value={kind} onChange={(event) => setKind(event.target.value)} className="rounded-lg border border-ink-200 px-2 py-2 text-sm">
          <option value="term">Término</option>
          <option value="person">Persona</option>
          <option value="product">Producto</option>
          <option value="acronym">Sigla</option>
          <option value="vendor">Proveedor</option>
        </select>
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
            <li key={device.id} className="flex items-center justify-between py-3">
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
            </li>
          ))}
        </ul>
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
  return (
    <Card>
      <h2 className="mb-3 font-semibold text-ink-900">Privacidad</h2>
      <div className="space-y-3 text-sm leading-relaxed text-ink-600">
        <p>
          <strong className="text-ink-800">El audio no se guarda.</strong> Echo procesa el audio en memoria
          solo el tiempo necesario para transcribirlo y lo descarta. No existen grabaciones almacenadas: lo
          que persiste es el transcript, los hablantes, las decisiones, tareas, resúmenes y el acta.
        </p>
        <p>
          <strong className="text-ink-800">Modo local (Echo Bridge):</strong> con el bridge instalado, el
          audio nunca sale de la computadora — solo el texto llega al servidor.
        </p>
        <p>
          <strong className="text-ink-800">Modo cloud:</strong> el audio viaja cifrado al proveedor de
          transcripción configurado, que lo procesa y Echo lo descarta de inmediato. Siempre se indica en la
          pantalla de la reunión qué modo está activo.
        </p>
        <p>
          <strong className="text-ink-800">Indicador de grabación:</strong> cuando hay captura activa, la UI
          (y el dispositivo ESP32) muestran «● Grabando». Nunca hay grabación oculta. Asegurate de que los
          participantes sepan que la reunión está siendo transcripta.
        </p>
        <p>
          <strong className="text-ink-800">Voice profiles:</strong> son opt-in y guardan solo un embedding
          matemático de la voz (no audio). Se pueden eliminar en cualquier momento.
        </p>
        <p>
          <strong className="text-ink-800">API keys:</strong> se guardan cifradas (Fernet/AES) y nunca se
          devuelven completas al navegador ni se registran en logs.
        </p>
      </div>
    </Card>
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
