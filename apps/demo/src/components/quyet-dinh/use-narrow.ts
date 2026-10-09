"use client";

import { useEffect, useState } from "react";

/** `true` below 768 px (the artboards' mobile breakpoint, `Mobile.dc.html`). */
export function useNarrow(query = "(max-width: 767px)"): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    const update = () => setNarrow(list.matches);
    update();
    list.addEventListener?.("change", update);
    return () => list.removeEventListener?.("change", update);
  }, [query]);
  return narrow;
}
