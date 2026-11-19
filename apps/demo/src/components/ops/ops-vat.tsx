"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { readAuthSession } from "../../lib/supabase-auth";
import { createBuilderApi, opsBuilderBase } from "../../lib/shopee-decisions/builder-api";
import { C, card } from "./ops-shell";

/**
 * "Thuế VAT" in Ops' Cài đặt shop (F6.3, owner 2026-11-19): the shop's default rate
 * (`vat_rate_default`) and a rate per product (`vat_rate`). A product's rate is written for the
 * item id and for every one of its variations, so a line with or without a variation reads it.
 * Writes go through the existing Ops rules routes (Vận hành+, audited); Xem only reads.
 */

export const VAT_RATES = [0, 5, 8, 10] as const;

export interface VatRates {
  readonly default: number | null;
  readonly rates: readonly { readonly scope_ref: string; readonly value: number }[];
}

export interface VatProduct {
  readonly item_id: string;
  readonly name: string;
}

export interface OpsVatApi {
  read(): Promise<VatRates>;
  put(key: "vat_rate" | "vat_rate_default", scope: string | null, value: number): Promise<void>;
  remove(key: "vat_rate" | "vat_rate_default", scope: string): Promise<void>;
  search(q: string): Promise<readonly VatProduct[]>;
  variationIds(itemId: string): Promise<readonly string[]>;
}

export function createOpsVatApi(shopId: string, token: string, fetchImpl: typeof fetch = fetch): OpsVatApi {
  const base = `/v1/ops/shops/${encodeURIComponent(shopId)}`;
  const call = async (path: string, init: RequestInit = {}): Promise<Response> => {
    const res = await fetchImpl(`${base}${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    });
    if (!res.ok) throw new Error(String(res.status));
    return res;
  };
  const builder = createBuilderApi({ base: opsBuilderBase(shopId), token, fetchImpl });
  return {
    read: async () => (await (await call("/vat-rates")).json()) as VatRates,
    put: async (key, scope, value) => {
      await call(`/rules/${key}`, { method: "PUT", body: JSON.stringify({ scope_ref: scope, value, set_by: "team" }) });
    },
    remove: async (key, scope) => {
      await call(`/rules/${key}${scope ? `?scope_ref=${encodeURIComponent(scope)}` : ""}`, { method: "DELETE" });
    },
    search: async (q) => (await builder.products({ q, limit: 8 })).products.map((p) => ({ item_id: p.item_id, name: p.name })),
    variationIds: async (itemId) => (await builder.variations(itemId)).variations.map((v) => v.variation_id),
  };
}

const itemOf = (scope: string): string => scope.split(":")[0] ?? scope;

export function OpsVat({
  shopId,
  canEdit,
  baseFetch,
  api,
}: {
  readonly shopId: string;
  readonly canEdit: boolean;
  readonly baseFetch?: typeof fetch;
  readonly api?: OpsVatApi;
}) {
  const client = useMemo(() => api ?? createOpsVatApi(shopId, readAuthSession()?.accessToken ?? "", baseFetch), [api, shopId, baseFetch]);
  const [data, setData] = useState<VatRates | null>(null);
  const [names, setNames] = useState<Readonly<Record<string, string>>>({});
  const [q, setQ] = useState("");
  const [found, setFound] = useState<readonly VatProduct[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await client.read());
    } catch {
      setError("Không tải được thuế VAT.");
    }
  }, [client]);
  useEffect(() => {
    let live = true;
    client
      .read()
      .then((d) => live && setData(d))
      .catch(() => live && setError("Không tải được thuế VAT."));
    return () => {
      live = false;
    };
  }, [client]);

  const guard = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch {
      setError("Không lưu được. Thử lại sau.");
    } finally {
      setBusy(false);
    }
  };

  const setDefault = (v: string) =>
    guard(async () => {
      if (v === "") {
        // an unset default is the rule row removed
        await client.remove("vat_rate_default", "");
      } else {
        await client.put("vat_rate_default", null, Number(v));
      }
    });

  const search = async (text: string) => {
    setQ(text);
    if (text.trim().length < 2) {
      setFound([]);
      return;
    }
    try {
      const rows = await client.search(text.trim());
      setFound(rows);
      setNames((n) => ({ ...n, ...Object.fromEntries(rows.map((p) => [p.item_id, p.name])) }));
    } catch {
      setFound([]);
    }
  };

  const setProduct = (p: VatProduct, rate: number) =>
    guard(async () => {
      const ids = await client.variationIds(p.item_id);
      await client.put("vat_rate", p.item_id, rate);
      for (const id of ids) await client.put("vat_rate", `${p.item_id}:${id}`, rate);
    });

  const removeProduct = (scopes: readonly string[]) =>
    guard(async () => {
      for (const s of scopes) await client.remove("vat_rate", s);
    });

  const grouped = useMemo(() => {
    const out = new Map<string, { value: number; scopes: string[] }>();
    for (const r of data?.rates ?? []) {
      const item = itemOf(r.scope_ref);
      const g = out.get(item) ?? { value: r.value, scopes: [] };
      if (r.scope_ref === item) g.value = r.value;
      g.scopes.push(r.scope_ref);
      out.set(item, g);
    }
    return [...out.entries()];
  }, [data]);

  const field = { font: "inherit", fontSize: 13, minHeight: 32, borderRadius: 8, border: `1px solid ${C.line}`, padding: "0 8px" } as const;
  const chip = { ...field, background: "#ffffff", cursor: "pointer", fontWeight: 600 } as const;
  return (
    <div data-testid="ops-vat" id="thue-vat" style={card}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Thuế VAT</h2>
      <label style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
        <span>Mặc định</span>
        <select aria-label="Thuế VAT mặc định" disabled={!canEdit || busy || !data} onChange={(e) => void setDefault(e.target.value)} style={field} value={data?.default === null || data?.default === undefined ? "" : String(data.default)}>
          <option value="">Chưa đặt</option>
          {VAT_RATES.map((r) => (
            <option key={r} value={r}>
              {r}%
            </option>
          ))}
        </select>
      </label>
      {canEdit ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <input aria-label="Tìm sản phẩm" onChange={(e) => void search(e.target.value)} placeholder="Tìm sản phẩm" style={{ ...field, minHeight: 36 }} type="search" value={q} />
          {found.length ? (
            <ul aria-label="Kết quả" style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
              {found.map((p) => (
                <li data-testid={`vat-found-${p.item_id}`} key={p.item_id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                  <span style={{ flex: 1 }}>{p.name}</span>
                  {VAT_RATES.map((r) => (
                    <button aria-label={`${p.name} ${r}%`} disabled={busy} key={r} onClick={() => void setProduct(p, r)} style={chip} type="button">
                      {r}%
                    </button>
                  ))}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {grouped.length ? (
        <ul aria-label="Thuế VAT theo sản phẩm" style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
          {grouped.map(([item, g]) => (
            <li data-testid={`vat-rate-${item}`} key={item} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
              <span style={{ flex: 1 }}>{names[item] ?? item}</span>
              <b>{g.value}%</b>
              {canEdit ? (
                <button aria-label={`Bỏ ${names[item] ?? item}`} disabled={busy} onClick={() => void removeProduct(g.scopes)} style={chip} type="button">
                  Bỏ
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {error ? (
        <p role="alert" style={{ margin: 0, color: C.red, fontSize: 13 }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
