"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import type { PersonaId, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import {
  DEFAULT_PERSONA_ID,
  persistPersonaId,
  readStoredPersonaId,
} from "./demo-persona";

interface DemoPersonaContextValue {
  personaId: PersonaId;
  persona: SellerPersona;
  isReady: boolean;
  setPersonaId: (id: PersonaId) => void;
}

const DemoPersonaContext = createContext<DemoPersonaContextValue | null>(null);

export function DemoPersonaProvider({ children }: { children: ReactNode }) {
  const [personaId, setPersonaIdState] = useState<PersonaId>(DEFAULT_PERSONA_ID);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    setPersonaIdState(readStoredPersonaId());
    setIsReady(true);
  }, []);

  const setPersonaId = useCallback((id: PersonaId) => {
    persistPersonaId(id);
    setPersonaIdState(id);
  }, []);

  const persona = useMemo(() => loadPersona(personaId), [personaId]);

  const value = useMemo(
    () => ({ personaId, persona, isReady, setPersonaId }),
    [personaId, persona, isReady, setPersonaId],
  );

  return (
    <DemoPersonaContext.Provider value={value}>{children}</DemoPersonaContext.Provider>
  );
}

export function useDemoPersona(): DemoPersonaContextValue {
  const ctx = useContext(DemoPersonaContext);
  if (!ctx) {
    throw new Error("useDemoPersona must be used within DemoPersonaProvider");
  }
  return ctx;
}

export function useDemoPersonaOptional(): DemoPersonaContextValue | null {
  return useContext(DemoPersonaContext);
}
