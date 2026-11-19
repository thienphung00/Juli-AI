"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { readAuthSession } from "../../lib/supabase-auth";
import { C, card } from "../ops/ops-shell";

export type StockAlertStatus = "off" | "preview" | "on";
export interface StockAlertSettings {
  readonly status: StockAlertStatus;
  readonly days: number;
}
export interface StockAlertApi {
  readonly get: () => Promise<StockAlertSettings>;
  readonly put: (body: { status?: StockAlertStatus; days?: number }) => Promise<StockAlertSettings>;
}

export const STATUS_CHOICES: readonly { readonly value: StockAlertStatus; readonly label: string }[] = [
  { value: "off", label: "Tắt" },
  { value: "preview", label: "Xem trước" },
  { value: "on", label: "Bật" },
];
export const MIN_DAYS = 1;
export const MAX_DAYS = 60;

/** `GET/PUT /v1/ops/shops/{id}/stock-alert`; a non-2xx answer throws the backend's sentence. */
export function createStockAlertApi(shopId: string, token: string, fetchImpl: typeof fetch = fetch): StockAlertApi {
  const url = `/v1/ops/shops/${encodeURIComponent(shopId)}/stock-alert`;
  const call = async (init: RequestInit): Promise<StockAlertSettings> => {
    const res = await fetchImpl(url, {
      ...init,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    });
    if (!res.ok) {
      let message = "Không lưu được. Bạn thử lại sau ít phút nhé.";
      try {
        const body = (await res.json()) as { detail?: { message?: unknown } | string };
        if (typeof body.detail === "string") message = body.detail;
        else if (typeof body.detail?.message === "string") message = body.detail.message;
      } catch {
        // keep the generic sentence
      }
      throw new Error(message);
    }
    return (await res.json()) as StockAlertSettings;
  };
  return { get: () => call({ method: "GET" }), put: (body) => call({ method: "PUT", body: JSON.stringify(body) }) };
}

/** "Báo cáo tồn kho" in Ops' Cài đặt shop: Tắt / Xem trước / Bật and "Số ngày cảnh báo" (1-60). */
export function OpsStockAlert({
  shopId,
  canEdit,
  baseFetch,
  api,
}: {
  readonly shopId: string;
  readonly canEdit: boolean;
  readonly baseFetch?: typeof fetch;
  readonly api?: StockAlertApi;
}) {
  const client = useMemo(
    () => api ?? createStockAlertApi(shopId, readAuthSession()?.accessToken ?? "", baseFetch),
    [api, shopId, baseFetch],
  );
  const [status, setStatus] = useState<StockAlertStatus>("off");
  const [days, setDays] = useState("7");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apply = useCallback((s: StockAlertSettings) => {
    setStatus(s.status);
    setDays(String(s.days));
  }, []);

  useEffect(() => {
    let live = true;
    client
      .get()
      .then((s) => {
        if (live) {
          apply(s);
          setLoaded(true);
        }
      })
      .catch((e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : "Không tải được.");
      });
    return () => {
      live = false;
    };
  }, [client, apply]);

  const n = Number(days);
  const valid = Number.isInteger(n) && n >= MIN_DAYS && n <= MAX_DAYS;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      apply(await client.put({ status, days: n }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không lưu được.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div data-testid="ops-stock-alert" style={card}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Báo cáo tồn kho</h2>
      <div aria-label="Báo cáo tồn kho" role="radiogroup" style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
        {STATUS_CHOICES.map((c) => (
          <label key={c.value} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 14 }}>
            <input
              checked={status === c.value}
              disabled={!canEdit || !loaded}
              name="stock-alert-status"
              onChange={() => setStatus(c.value)}
              type="radio"
              value={c.value}
            />
            {c.label}
          </label>
        ))}
      </div>
      <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 14 }}>
        Số ngày cảnh báo
        <input
          disabled={!canEdit || !loaded}
          max={MAX_DAYS}
          min={MIN_DAYS}
          onChange={(e) => setDays(e.target.value)}
          style={{ width: 72, minHeight: 36 }}
          type="number"
          value={days}
        />
      </label>
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <button disabled={!canEdit || !loaded || !valid || saving} onClick={() => void save()} type="button">
          Lưu
        </button>
        {error ? (
          <span role="alert" style={{ fontSize: 13, color: C.pink }}>
            {error}
          </span>
        ) : null}
      </div>
    </div>
  );
}
