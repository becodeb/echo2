import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, setAccessToken, setActiveOrg, getActiveOrg } from "../api/client";
import type { OrgOut, SessionOut, UserOut } from "../api/types";
import { useQueryClient } from "@tanstack/react-query";
import { clearPersistedCache, persistCache, restorePersistedCache } from "../lib/persistCache";

interface AuthState {
  loading: boolean;
  user: UserOut | null;
  organizations: OrgOut[];
  activeOrg: OrgOut | null;
  login: (email: string, password: string) => Promise<SessionOut>;
  register: (name: string, email: string, password: string) => Promise<SessionOut>;
  logout: () => Promise<void>;
  createOrganization: (name: string) => Promise<OrgOut>;
  switchOrg: (orgId: string) => void;
  refreshSession: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<UserOut | null>(null);
  const [organizations, setOrganizations] = useState<OrgOut[]>([]);
  const [activeOrgId, setActiveOrgId] = useState<string | null>(getActiveOrg());

  const queryClient = useQueryClient();
  const restoredFor = useRef<string | null>(null);

  const applySession = useCallback((session: SessionOut) => {
    // Antes de dibujar: lo último que vio esta persona aparece al instante.
    if (restoredFor.current !== session.user.id) {
      restoredFor.current = session.user.id;
      restorePersistedCache(queryClient, session.user.id);
    }
    setAccessToken(session.access_token);
    setUser(session.user);
    setOrganizations(session.organizations);
    setActiveOrgId((current) => {
      const valid = session.organizations.find((org) => org.id === current);
      const next = valid?.id ?? session.organizations[0]?.id ?? null;
      setActiveOrg(next);
      return next;
    });
  }, [queryClient]);

  useEffect(() => {
    if (!user) return;
    return persistCache(queryClient, user.id);
  }, [queryClient, user]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/api/auth/refresh", {
          method: "POST",
          headers: { "x-echo-client": "web" },
          credentials: "include",
        });
        // 204: no hay sesión (la landing pública); no es un error.
        if (response.ok && response.status !== 204 && !cancelled) {
          applySession(await response.json());
        }
      } catch {
        /* sin sesión */
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    const onLogout = () => {
      clearPersistedCache();
      queryClient.clear();
      restoredFor.current = null;
      setUser(null);
      setOrganizations([]);
      setAccessToken(null);
    };
    const onSession = (event: Event) => {
      applySession((event as CustomEvent).detail as SessionOut);
    };
    window.addEventListener("echo:logout", onLogout);
    window.addEventListener("echo:session", onSession);
    return () => {
      cancelled = true;
      window.removeEventListener("echo:logout", onLogout);
      window.removeEventListener("echo:session", onSession);
    };
  }, [applySession, queryClient]);

  const login = useCallback(
    async (email: string, password: string) => {
      const session = await api<SessionOut>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
        skipOrg: true,
      });
      applySession(session);
      return session;
    },
    [applySession],
  );

  const register = useCallback(
    async (name: string, email: string, password: string) => {
      const session = await api<SessionOut>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ name, email, password }),
        skipOrg: true,
      });
      applySession(session);
      return session;
    },
    [applySession],
  );

  const logout = useCallback(async () => {
    try {
      await api("/api/auth/logout", { method: "POST", skipOrg: true });
    } finally {
      clearPersistedCache();
      queryClient.clear();
      restoredFor.current = null;
      setAccessToken(null);
      setUser(null);
      setOrganizations([]);
    }
  }, [queryClient]);

  const createOrganization = useCallback(async (name: string) => {
    const org = await api<OrgOut>("/api/auth/organizations", {
      method: "POST",
      body: JSON.stringify({ name }),
      skipOrg: true,
    });
    setOrganizations((current) => [...current, org]);
    setActiveOrg(org.id);
    setActiveOrgId(org.id);
    return org;
  }, []);

  const switchOrg = useCallback((orgId: string) => {
    setActiveOrg(orgId);
    setActiveOrgId(orgId);
  }, []);

  const refreshSession = useCallback(async () => {
    const session = await api<SessionOut>("/api/auth/me", { skipOrg: true });
    applySession(session);
  }, [applySession]);

  const value = useMemo<AuthState>(
    () => ({
      loading,
      user,
      organizations,
      activeOrg: organizations.find((org) => org.id === activeOrgId) ?? null,
      login,
      register,
      logout,
      createOrganization,
      switchOrg,
      refreshSession,
    }),
    [loading, user, organizations, activeOrgId, login, register, logout, createOrganization, switchOrg, refreshSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth fuera de AuthProvider");
  return context;
}
