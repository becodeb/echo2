import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { MyDriveOut } from "../api/types";
import { PillSwitch, SettingRow } from "./SettingRows";

/** Estado del Drive personal (adonde van las grabaciones de cada uno). */
export function useMyDrive(enabled = true) {
  return useQuery({
    queryKey: ["my-drive"],
    queryFn: () => api<MyDriveOut>("/api/me/drive", { skipOrg: true }),
    enabled,
    staleTime: 60_000,
  });
}

/**
 * "Grabar el audio completo": además de transcribir, guarda la reunión entera.
 * Dice adónde va a ir a parar, que es lo primero que alguien se pregunta.
 */
export function RecordToggle({
  checked,
  onChange,
  disabled = false,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  const { data: drive } = useMyDrive();
  return (
    <SettingRow
      disabled={disabled}
      label="Grabar el audio completo"
      control={<PillSwitch checked={checked} onChange={onChange} label="Grabar el audio completo" disabled={disabled} />}
      hint={
        <>
          {drive?.connected ? (
            <>Al terminar se guarda en tu Google Drive ({drive.connected_email}) y se borra de Echo.</>
          ) : (
            <>
              Al terminar lo podés descargar durante 48 horas; después se borra.{" "}
              {drive?.enabled && (
                <Link to="/settings/my-drive" className="font-medium text-ink-700 underline-offset-2 hover:underline">
                  Conectá tu Drive
                </Link>
              )}
              {drive?.enabled && " para que se guarde solo."}
            </>
          )}
          {checked && " Avisale a los participantes que se graba."}
        </>
      }
    />
  );
}
