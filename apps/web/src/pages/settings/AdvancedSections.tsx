import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Select } from "../../components/Select";
import { Switch } from "../../components/Toggles";
import { Button, Input, Modal, Spinner } from "../../components/ui";
import { Block, ErrorText } from "./parts";

// ── Diccionario ──────────────────────────────────────────────────

export function DictionarySection() {
  const queryClient = useQueryClient();
  const [term, setTerm] = useState("");
  const [kind, setKind] = useState("term");

  const { data: entries } = useQuery({
    queryKey: ["dictionary"],
    queryFn: () => api<{ id: string; term: string; kind: string }[]>("/api/org/dictionary"),
  });

  const add = useMutation({
    mutationFn: () => api("/api/org/dictionary", { method: "POST", body: JSON.stringify({ term, kind }) }),
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
    <Block
      id="dictionary-terms"
      hint="Nombres propios, productos y siglas de tu organización. El motor de transcripción los tiene en cuenta y la IA los usa de contexto."
    >
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
          aria-label="Término"
          className="min-w-[180px] flex-1 rounded-xl border border-ink-200 px-3 py-2 text-sm focus:border-accent-500 focus:outline-none"
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
    </Block>
  );
}

// ── Dispositivos ─────────────────────────────────────────────────

export function DevicesSection() {
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
    mutationFn: () => api("/api/devices/claim", { method: "POST", body: JSON.stringify({ code, name: deviceName }) }),
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
    <Block
      id="devices-list"
      title="Echo Devices"
      action={<Button variant="soft" onClick={() => setShowClaim(true)}>Vincular dispositivo</Button>}
    >
      {devices?.length === 0 && (
        <p className="text-sm text-ink-400">
          Sin dispositivos. El Echo Device muestra un código en su pantalla al encenderse: usalo acá para vincularlo a
          la sede.
        </p>
      )}
      <ul className="divide-y divide-ink-100">
        {devices?.map((device) => (
          <li key={device.id} className="space-y-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
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
      {setMinors.isError && <ErrorText error={setMinors.error} fallback="No se pudo cambiar" />}

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
          {claim.isError && <ErrorText error={claim.error} fallback="Error" />}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setShowClaim(false)}>Cancelar</Button>
            <Button type="submit" disabled={claim.isPending}>
              {claim.isPending ? <Spinner /> : "Vincular"}
            </Button>
          </div>
        </form>
      </Modal>
    </Block>
  );
}
