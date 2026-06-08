"use client";

import { useCallback, useEffect, useState } from "react";
import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import { SHOP_PROGRESS_UPDATED_EVENT } from "./constants";
import { loadShopProgress } from "./tracker";
import type { ShopProgressSession } from "./types";

export function useShopProgress(personaId: PersonaId): ShopProgressSession {
  const [progress, setProgress] = useState<ShopProgressSession>(() =>
    loadShopProgress(personaId),
  );

  const refresh = useCallback(() => {
    setProgress(loadShopProgress(personaId));
  }, [personaId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ personaId: PersonaId }>).detail;
      if (detail?.personaId === personaId) {
        refresh();
      }
    };

    window.addEventListener(SHOP_PROGRESS_UPDATED_EVENT, handler);
    return () => window.removeEventListener(SHOP_PROGRESS_UPDATED_EVENT, handler);
  }, [personaId, refresh]);

  return progress;
}
