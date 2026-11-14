// After an update or a reinstall (Connector 0.3.19), Chrome does not run the content scripts again
// in Seller Centre tabs that were already open: their relay is gone, so the daily sync and the
// page's own answers stop reaching the service worker until the seller reloads. The service worker
// injects the relay again into each such tab. The page hook lives in the page itself (MAIN world)
// and outlives an update; it is injected only into a tab that has none (fetch still native), so a
// tab never ends up with two hooks sending every request twice. Re-injection never starts a
// listing fill: the relay is told it was re-injected and skips that part.

export interface HookProbe {
  /** `window.fetch` is still the browser's own (no hook of ours, nor any other wrapper). */
  nativeFetch: boolean;
}

/** What to inject into one already-open Seller Centre tab. */
export function reinjectPlan(probe: HookProbe | undefined): { hook: boolean; relay: boolean } {
  if (!probe) return { hook: false, relay: false };
  return { hook: probe.nativeFetch === true, relay: true };
}

/** Runs in the page (MAIN world): is fetch still native? Self-contained (serialised by Chrome). */
export function probeHook(): HookProbe {
  return { nativeFetch: /\[native code\]/.test(Function.prototype.toString.call(window.fetch)) };
}

/** Runs in the extension's isolated world before the relay: marks this injection as a re-injection. */
export function markReinjected(): boolean {
  (globalThis as Record<string, unknown>).__juliReinjected = true;
  return true;
}

export interface ReinjectDeps {
  sellerCentreTabs(): Promise<{ id?: number; discarded?: boolean }[]>;
  probe(tabId: number): Promise<HookProbe | undefined>;
  injectHook(tabId: number): Promise<void>;
  injectRelay(tabId: number): Promise<void>;
}

/** Re-inject into every open, loaded Seller Centre tab; a tab that refuses is skipped. Returns the count. */
export async function reinjectSellerCentreTabs(deps: ReinjectDeps): Promise<number> {
  let count = 0;
  for (const tab of await deps.sellerCentreTabs().catch(() => [])) {
    if (tab.id === undefined || tab.discarded) continue;
    try {
      const plan = reinjectPlan(await deps.probe(tab.id));
      if (!plan.relay) continue;
      if (plan.hook) await deps.injectHook(tab.id);
      await deps.injectRelay(tab.id);
      count += 1;
    } catch {
      // a tab that is loading, crashed or not ours to script: skipped
    }
  }
  return count;
}
