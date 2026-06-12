import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { apiLogin, apiLogout, apiMe } from "./auth.api";
import { ApiError } from "../api/client";
import type { User } from "../types";

type AuthValue = {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiMe()
      .then(setUser)
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401)) {
          console.error("me failed", e); // не 401 — лог, но всё равно «не залогинен»
        }
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  async function login(username: string, password: string) {
    setUser(await apiLogin(username, password));
  }
  async function logout() {
    await apiLogout();
    setUser(null);
  }

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
