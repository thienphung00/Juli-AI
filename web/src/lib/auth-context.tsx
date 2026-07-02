"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  UI_ONLY_DEMO_SHOP,
  UI_ONLY_DEMO_TOKEN,
  UI_ONLY_DEMO_USER,
} from "./ui-only";

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: { id: string; phone: string } | null;
  token: string | null;
}

interface AuthContextValue extends AuthState {
  loginAsReviewer: () => Promise<void>;
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

  const loginAsReviewer = useCallback(async () => {
    localStorage.setItem("access_token", UI_ONLY_DEMO_TOKEN);
    localStorage.setItem("user", JSON.stringify(UI_ONLY_DEMO_USER));
    localStorage.setItem("active_shop_id", UI_ONLY_DEMO_SHOP.id);
    setState({
      isAuthenticated: true,
      isLoading: false,
      user: UI_ONLY_DEMO_USER,
      token: UI_ONLY_DEMO_TOKEN,
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
    <AuthContext.Provider value={{ ...state, loginAsReviewer, logout }}>
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
