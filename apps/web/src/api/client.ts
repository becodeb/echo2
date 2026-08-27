/**
 * Cliente HTTP de Echo: access token en memoria, refresh automático con
 * cookie httpOnly, header de organización activa en cada request.
 */

let accessToken: string | null = null;
let activeOrgId: string | null = localStorage.getItem("echo_org") || null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

export function setActiveOrg(orgId: string | null) {
  activeOrgId = orgId;
  if (orgId) localStorage.setItem("echo_org", orgId);
  else localStorage.removeItem("echo_org");
}

export function getActiveOrg() {
  return activeOrgId;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let refreshPromise: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const response = await fetch("/api/auth/refresh", {
          method: "POST",
          headers: { "x-echo-client": "web" },
          credentials: "include",
        });
        if (!response.ok) return false;
        const data = await response.json();
        accessToken = data.access_token;
        window.dispatchEvent(new CustomEvent("echo:session", { detail: data }));
        return true;
      } catch {
        return false;
      } finally {
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit & { skipOrg?: boolean; retry?: boolean } = {},
): Promise<T> {
  const { skipOrg, retry = true, ...init } = options;
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  if (!(init.body instanceof FormData) && init.body) {
    headers["Content-Type"] = "application/json";
  }
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  if (activeOrgId && !skipOrg) headers["X-Organization-Id"] = activeOrgId;
  headers["x-echo-client"] = "web";

  const response = await fetch(path, { ...init, headers, credentials: "include" });

  if (response.status === 401 && retry) {
    const refreshed = await tryRefresh();
    if (refreshed) return api<T>(path, { ...options, retry: false });
    window.dispatchEvent(new Event("echo:logout"));
    throw new ApiError(401, "Sesión expirada");
  }

  if (!response.ok) {
    let message = `Error ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      /* sin body json */
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function wsUrl(path: string): string {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}${path}`;
}
