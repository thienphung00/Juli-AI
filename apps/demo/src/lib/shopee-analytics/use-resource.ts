"use client";

import { useEffect, useState } from "react";

import { refusalOf, type ApiRefusal } from "./client";

export type Resource<T> =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: T }
  | { readonly status: "refused"; readonly refusal: ApiRefusal; readonly message: string };

/**
 * Loads one payload when `key` changes. A refusal (not a Shopee shop, no data, unknown product,
 * invalid window, failure) is a state of its own, never an empty page.
 */
export function useResource<T>(load: () => Promise<T>, key: string): Resource<T> {
  const [state, setState] = useState<{ key: string; value: Resource<T> } | null>(null);
  useEffect(() => {
    let live = true;
    load()
      .then((data) => live && setState({ key, value: { status: "ready", data } }))
      .catch((error: unknown) => {
        if (!live) return;
        setState({
          key,
          value: {
            status: "refused",
            refusal: refusalOf(error),
            message: error instanceof Error ? error.message : "",
          },
        });
      });
    return () => {
      live = false;
    };
    // `load` is rebuilt every render; `key` is what says the request changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state && state.key === key ? state.value : { status: "loading" };
}
