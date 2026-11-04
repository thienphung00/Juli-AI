"use client";

import { useState } from "react";

import { useReco } from "../../lib/shopee-decisions/context";
import { errorText } from "./ui";

/** Juli Ops: generate cards from the latest numbers (drafts), send the drafts to the shop, re-run stale cards. */
export function StaffBar({ onChanged }: { readonly onChanged: () => void }) {
  const host = useReco();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const act = async (label: string, call: () => Promise<string>) => {
    setBusy(true);
    setMsg(null);
    try {
      setMsg(`${label}: ${await call()}`);
      onChanged();
    } catch (e) {
      setMsg(`${label}: ${errorText(e)}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="sa-card sd-staff" data-testid="sd-staffbar">
      <div className="sa-card__head">
        <h2 className="sa-h2">Việc của Ops</h2>
        <span className="sa-hint">Tạo thẻ từ số liệu mới nhất (nháp), gửi cho shop, hoặc tính lại thẻ khi thông số shop đổi.</span>
      </div>
      <div className="sd-actions">
        <button className="sa-btn sa-btn--primary" disabled={busy} onClick={() => void act("Tạo đề xuất", async () => `${(await host.reco.generate({ topN: 10 })).persisted} thẻ nháp`)} type="button">
          Tạo đề xuất
        </button>
        <button className="sa-btn" disabled={busy} onClick={() => void act("Gửi cho shop", async () => `${(await host.reco.publish(null)).sent.length} thẻ đã gửi`)} type="button">
          Gửi tất cả nháp cho shop
        </button>
        <button className="sa-btn" disabled={busy} onClick={() => void act("Tính lại thẻ cũ", async () => JSON.stringify(await host.reco.rerunStale()))} type="button">
          Tính lại thẻ cũ
        </button>
      </div>
      {msg ? (
        <p className="sa-hint" data-testid="sd-staff-msg" role="status">
          {msg}
        </p>
      ) : null}
    </section>
  );
}
