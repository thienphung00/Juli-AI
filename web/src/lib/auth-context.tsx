"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, type SessionResponse } from "./api-client";
import {
  UI_ONLY_DEMO_SHOP,
  UI_ONLY_DEMO_TOKEN,
  UI_ONLY_DEMO_USER,
  isUiOnly,
} from "./ui-only";

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: { id: string; phone: string } | null;
  token: string | null;
}

interface AuthContextValue extends AuthState {
  sendOtp: (phone: string) => Promise<void>;
  verifyOtp: (phone: string, code: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    isAuthenticated: false,
    isLoading: true,
    user: null,
    token: null,
  });

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    const userJson = localStorage.getItem("user");
    if (token && userJson) {
      try {
        const user = JSON.parse(userJson);
        setState({ isAuthenticated: true, isLoading: false, user, token });
      } catch {
        localStorage.removeItem("access_token");
        localStorage.removeItem("user");
        setState((s) => ({ ...s, isLoading: false }));
      }
    } else {
      setState((s) => ({ ...s, isLoading: false }));
    }
  }, []);

  const sendOtp = useCallback(async (phone: string) => {
    if (isUiOnly) {
      if (!phone.trim()) {
        throw new Error("Phone required");
      }
      return;
    }
    await api.auth.sendOtp(phone);
  }, []);

  const verifyOtp = useCallback(async (phone: string, code: string) => {
    const session: SessionResponse = isUiOnly
      ? {
          access_token: UI_ONLY_DEMO_TOKEN,
          user: {
            ...UI_ONLY_DEMO_USER,
            phone: phone.trim() || UI_ONLY_DEMO_USER.phone,
          },
        }
      : await api.auth.verifyOtp(phone, code);
    localStorage.setItem("access_token", session.access_token);
    localStorage.setItem("user", JSON.stringify(session.user));
    if (isUiOnly) {
      localStorage.setItem("active_shop_id", UI_ONLY_DEMO_SHOP.id);
    }
    setState({
      isAuthenticated: true,
      isLoading: false,
      user: session.user,
      token: session.access_token,
    });
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("user");
    localStorage.removeItem("active_shop_id");
    setState({
      isAuthenticated: false,
      isLoading: false,
      user: null,
      token: null,
    });
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, sendOtp, verifyOtp, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
