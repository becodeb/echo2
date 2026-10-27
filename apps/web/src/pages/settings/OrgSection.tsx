import { useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Select } from "../../components/Select";
import { Badge, Button, Input, Spinner } from "../../components/ui";
import { useAuth } from "../../state/auth";
import { CreateOrJoin } from "../OnboardingOrg";
import { Block, ErrorText } from "./parts";

const ROLE_LABEL: Record<string, string> = {
  owner: "Dueño",
  admin: "Administra",
  member: "Miembro",
  viewer: "Solo lectura",
};

/** Desde la cuenta individual: sumarse al colegio con un código, o dar de alta la institución. */
function JoinOrCreate() {
  const [mode, setMode] = useState<"create" | "join">("join");
  return (
    <Block
      id="org-join"
      title="¿Tu colegio usa Echo?"
      hint="Unite con el código de invitación que te pasen, o creá la organización de tu institución. Tu cuenta individual sigue estando: cambiás entre las dos desde el menú."
    >
      <CreateOrJoin mode={mode} onMode={setMode} />
    </Block>
  );
}

export function OrgSection() {
  const { activeOrg } = useAuth();
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
    <div>
      <Block
        title={activeOrg?.name}
        hint={
          activeOrg?.is_personal
            ? "Tu cuenta individual."
            : `Tu rol: ${ROLE_LABEL[activeOrg?.role ?? ""] ?? activeOrg?.role}.`
        }
      />

      {activeOrg?.is_personal && <JoinOrCreate />}

      <Block id="org-members" title="Miembros">
        <ul className="divide-y divide-ink-100">
          {members?.map((member) => (
            <li key={member.id} className="flex items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-ink-800">{member.name}</p>
                <p className="truncate text-xs text-ink-400">{member.email}</p>
              </div>
              <Badge tone={member.role === "owner" ? "indigo" : "gray"}>{ROLE_LABEL[member.role] ?? member.role}</Badge>
            </li>
          ))}
        </ul>
      </Block>

      <Block
        id="org-invite"
        title="Invitar a alguien"
        hint="Le llega un código para entrar a la sede con el rol que elijas."
      >
        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            invite.mutate();
          }}
          className="flex flex-wrap items-end gap-2"
        >
          <div className="min-w-52 flex-1">
            <Input
              label="Email"
              type="email"
              placeholder="persona@colegio.edu.ar"
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
              { value: "member", label: "Miembro" },
              { value: "admin", label: "Administra" },
              { value: "viewer", label: "Solo lectura" },
            ]}
            className="w-32 shrink-0"
          />
          <Button type="submit" disabled={invite.isPending}>
            {invite.isPending ? <Spinner /> : "Invitar"}
          </Button>
        </form>
        {invite.isError && <ErrorText error={invite.error} fallback="Error" />}
        {lastInviteToken && (
          <div className="mt-3 rounded-xl bg-ink-50 p-3 text-sm">
            <p className="mb-1 font-medium text-ink-700">Invitación creada. Compartí este código:</p>
            <code className="break-all text-xs text-ink-600">{lastInviteToken}</code>
            <p className="mt-1 text-xs text-ink-400">
              La persona lo ingresa al registrarse en «Tengo una invitación». Expira en 7 días.
            </p>
          </div>
        )}
      </Block>
    </div>
  );
}
