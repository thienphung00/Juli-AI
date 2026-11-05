"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { DASH, fmt, pp, vnd } from "../../../lib/shopee-analytics/format";
import type { BuilderApi, BuilderEvaluation, BuilderOutcome, BuilderVersion, ChooseResult } from "../../../lib/shopee-decisions/builder-api";
import { SERVER_KIND_NAMES, bandText, breachesOfOutcome, breakEvenText, metricValue, refusalText, type Forms, type Kind92 } from "../../../lib/shopee-decisions/builder-p92";
import type { Breach } from "../../../lib/shopee-decisions/types";
import { ackText, breachWarnLines } from "../../../lib/shopee-decisions/versions";
import { TextChip } from "../../shopee-analytics/ui";
import { NavLink, errorText } from "../ui";
import { BreachDialog } from "../versions";
import { BasisChip, chuaTinh, costText } from "./results";

/**
 * SO SÁNH PHƯƠNG ÁN (artboards `SoSanhPhuongAn` / `…Mobile`, B-5): up to 4 versions of any kinds side by side
 * (`POST /builder/compare`, nothing saved), the same four numbers for all, then each version's driver metrics.
 * "Chọn" sends the version to Quyết định as a manual card (`POST /builder/choose`); a floor or spend-cap breach
 * opens the P91 warning ("Vẫn tiếp tục") and is sent again with `acknowledge_breaches`.
 */

export interface Entry {
  readonly id: number;
  readonly kind: Kind92;
  readonly forms: Forms;
  readonly version: BuilderVersion;
}

type Load = { readonly key: string; readonly state: { readonly status: "ready"; readonly result: BuilderEvaluation } | { readonly status: "error"; readonly message: string } };

interface Saved {
  readonly index: number;
  readonly result: ChooseResult;
  readonly ack: string | null;
}

function kindOf(e: Entry): string {
  return SERVER_KIND_NAMES[String(e.version.kind)] ?? String(e.version.kind);
}

interface RowDef {
  readonly key: string;
  readonly label: string;
  readonly sub?: string;
  readonly cell: (o: BuilderOutcome) => ReactNode;
}

const money = (o: BuilderOutcome, pick: "gmv" | "orders" | "profit"): ReactNode => {
  if (pick === "profit" && chuaTinh(o)) return <b>chưa tính</b>;
  const b = bandText(o.delta?.[pick], pick === "orders" ? "orders" : "vnd");
  return (
    <>
      <b>{b.main}</b>
      <span>{pick === "orders" && o.delta?.orders_note ? o.delta.orders_note : b.range}</span>
    </>
  );
};

function rowsFor(): RowDef[] {
  return [
    {
      key: "cost",
      label: "Chi phí của thay đổi",
      sub: "ở mức dùng dự kiến",
      cell: (o) => (
        <>
          <b>{costText(o)}</b>
          {o.cost?.label ? <span>{o.cost.label}</span> : null}
        </>
      ),
    },
    { key: "dgmv", label: "Δ GMV", sub: "30 ngày", cell: (o) => money(o, "gmv") },
    { key: "dorders", label: "Δ đơn", sub: "30 ngày", cell: (o) => money(o, "orders") },
    { key: "dprofit", label: "Δ lợi nhuận", sub: "30 ngày", cell: (o) => money(o, "profit") },
    {
      key: "margin",
      label: "Biên sau",
      sub: "trên GMV",
      cell: (o) =>
        chuaTinh(o) ? (
          <b>chưa tính</b>
        ) : (
          <>
            <b>{pp(o.margin_after_pct ?? null, 1)}</b>
            <span>hôm nay {pp(o.margin_before_pct ?? null, 1)}</span>
          </>
        ),
    },
    { key: "breakeven", label: "Hoà vốn", sub: "để lợi nhuận không giảm", cell: (o) => <span>{breakEvenText(o)}</span> },
    {
      key: "drivers",
      label: "Chỉ số chính",
      sub: "đo sau khi chạy · CTOR = đơn ÷ lượt nhấp",
      cell: (o) => (
        <ul className="p2-cmp__drivers">
          {(o.driver?.metrics ?? []).map((m) => (
            <li key={m.key}>
              <span>{m.label}</span> {metricValue(m.unit, m.before)} → {m.after_p50 === null ? "chưa ước tính" : metricValue(m.unit, m.after_p50)}
            </li>
          ))}
        </ul>
      ),
    },
    { key: "basis", label: "Cơ sở ước tính", sub: "cho từng phương án", cell: (o) => <BasisChip outcome={o} /> },
    {
      key: "warn",
      label: "Cảnh báo",
      sub: "chỉ báo, không chặn",
      cell: (o) => {
        const b = breachesOfOutcome(o);
        return b.length > 0 ? (
          <span className="p2-cmp__bad">
            <b>{b.some((x) => x.type === "floor") ? "Chạm giá sàn" : "Vượt trần chi"}</b>
            {breachWarnLines(b as Breach[]).map((l, i) => (
              <span key={i}>{l}</span>
            ))}
          </span>
        ) : (
          <span className="sd-muted">{o.warnings?.some((w) => w.type === "cost_unknown") ? "Chưa có giá vốn" : "Trên giá sàn"}</span>
        );
      },
    },
  ];
}

export function CompareView({
  api,
  entries,
  readOnly,
  costLink,
  narrow,
  planHref,
  staffDraft,
  onEdit,
  onRemove,
  onBack,
  onAdd,
}: {
  readonly api: BuilderApi;
  readonly entries: readonly Entry[];
  readonly readOnly: boolean;
  readonly costLink: string;
  readonly narrow: boolean;
  readonly planHref: string | null;
  readonly staffDraft: boolean;
  readonly onEdit: (i: number) => void;
  readonly onRemove: (i: number) => void;
  readonly onBack: () => void;
  readonly onAdd: () => void;
}) {
  const versions = useMemo(() => entries.map((e) => ({ ...e.version, label: e.version.label })), [entries]);
  const key = JSON.stringify(versions);
  const [load, setLoad] = useState<Load | null>(null);
  const seq = useRef(0);
  const [warn, setWarn] = useState<{ readonly index: number; readonly breaches: readonly Breach[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState<Saved | null>(null);
  const [primary, setPrimary] = useState(false);

  useEffect(() => {
    if (versions.length === 0) return;
    const n = ++seq.current;
    const call = versions.length >= 2 ? api.compare(versions) : api.evaluate(versions);
    call.then(
      (result) => n === seq.current && setLoad({ key, state: { status: "ready", result } }),
      (e: unknown) => n === seq.current && setLoad({ key, state: { status: "error", message: errorText(e) } }),
    );
    // `key` says the versions changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const current = load?.key === key ? load.state : null;
  const result = current?.status === "ready" ? current.result : null;
  const outcomes = result?.versions ?? [];
  const rows = rowsFor();

  const choose = async (index: number, ack: boolean, breaches: readonly Breach[]) => {
    setBusy(true);
    setErr(null);
    try {
      const out = await api.choose({ versions, chosen: index, primary, acknowledgeBreaches: ack });
      setWarn(null);
      setSaved({ index, result: out, ack: ack && breaches.length > 0 ? ackText(breaches, new Date().toISOString()) : null });
    } catch (e) {
      if (e instanceof ShopeeApiError && e.code === "reco_breach_not_acknowledged" && Array.isArray(e.detail?.["breaches"])) setWarn({ index, breaches: e.detail["breaches"] as Breach[] });
      else setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const onChoose = (index: number) => {
    const o = outcomes[index];
    const b = o ? (breachesOfOutcome(o) as Breach[]) : [];
    if (b.length > 0) setWarn({ index, breaches: b });
    else void choose(index, false, []);
  };

  const today = result?.today;
  const best = result?.best_profit_p50 ?? null;
  const style = { ["--p2-cols" as string]: entries.length } as React.CSSProperties;
  const head = (e: Entry, i: number) => (
    <div className="p2-cmp__head" key={e.id}>
      <b>P{i + 1}</b>
      <TextChip tone="pink">{kindOf(e)}</TextChip>
      <span>{String(e.version.label ?? "")}</span>
      {best === i ? <TextChip tone="up">lợi nhuận tốt nhất</TextChip> : null}
      <span className="p2-cmp__tools">
        <button className="sa-link p2-linkbtn" onClick={() => onEdit(i)} type="button">
          Sửa
        </button>
        <button aria-label={`Xoá P${i + 1}`} className="sa-link p2-linkbtn" onClick={() => onRemove(i)} type="button">
          Xoá
        </button>
      </span>
    </div>
  );
  const cellOf = (r: RowDef, i: number) => {
    const o = outcomes[i];
    if (!o) return <span className="sd-muted">{DASH}</span>;
    if (!o.ok) return <span className="sd-error">{r.key === "cost" ? refusalText(o) : DASH}</span>;
    return r.cell(o);
  };

  return (
    <section className="sa-card p2-compare" data-testid="p2-compare">
      <div className="sa-card__head">
        <h2 className="sa-h2">So sánh tối đa 4 phương án, loại nào cũng được</h2>
        <span className="sa-hint">{narrow ? "Vuốt ngang để xem từng phương án." : "30 ngày, dự kiến. Cùng bốn con số cho mọi phương án, rồi chỉ số chính của từng loại. Mỗi ô có khoảng thấp – cao. Hoà vốn luôn hiện."}</span>
      </div>
      {today ? (
        <p className="sa-hint" data-testid="p2-today">
          Hôm nay: {fmt(today.orders_30d)} đơn · GMV {vnd(today.gmv_30d)} · biên {pp(today.margin_pct, 1)} · AOV {vnd(today.aov)}
        </p>
      ) : null}
      {current === null ? (
        <p className="sa-hint" role="status">
          Đang tính…
        </p>
      ) : null}
      {current?.status === "error" ? (
        <p className="sd-error" role="alert">
          {current.message}
        </p>
      ) : null}
      {result && !narrow ? (
        <div className="p2-cmp" data-testid="p2-cmp-table" style={style}>
          <div className="p2-cmp__corner" />
          {entries.map(head)}
          {rows.map((r) => (
            <div className="p2-cmp__line" data-testid={`p2-row-${r.key}`} key={r.key}>
              <div className="p2-cmp__label">
                <b>{r.label}</b>
                {r.sub ? <span>{r.sub}</span> : null}
              </div>
              {entries.map((e, i) => (
                <div className={`p2-cmp__cell ${r.key === "warn" && outcomes[i] && breachesOfOutcome(outcomes[i]!).length > 0 ? "p2-cmp__cell--bad" : ""}`} data-testid={`p2-${r.key}-${i + 1}`} key={e.id}>
                  {cellOf(r, i)}
                </div>
              ))}
            </div>
          ))}
          <div className="p2-cmp__line">
            <div className="p2-cmp__label" />
            {entries.map((e, i) => (
              <div className="p2-cmp__cell" key={e.id}>
                <button className="sa-btn sa-btn--primary" data-testid={`p2-choose-${i + 1}`} disabled={readOnly || busy || !outcomes[i]?.ok || saved !== null} onClick={() => onChoose(i)} type="button">
                  Chọn P{i + 1}
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {result && narrow ? (
        <div className="sb-swipe" data-testid="p2-swipe">
          {entries.map((e, i) => (
            <div className="sb-swipe__card" key={e.id}>
              {head(e, i)}
              {rows.map((r) => (
                <div className="p2-swipe__row" key={r.key}>
                  <span className="p2-swipe__label">{r.label}</span>
                  <div className="p2-cmp__cell" data-testid={`p2-${r.key}-${i + 1}`}>{cellOf(r, i)}</div>
                </div>
              ))}
              <button className="sa-btn sa-btn--primary" data-testid={`p2-choose-${i + 1}`} disabled={readOnly || busy || !outcomes[i]?.ok || saved !== null} onClick={() => onChoose(i)} type="button">
                Chọn P{i + 1}
              </button>
            </div>
          ))}
        </div>
      ) : null}
      {result?.versions.some((o) => o.ok && o.cost_known === false) ? (
        <p className="sa-hint">
          Có sản phẩm chưa có giá vốn: lợi nhuận và biên “chưa tính”. <Link href={costLink}>Nhập giá vốn ở Cài đặt › Thông số shop ›</Link>
        </p>
      ) : null}
      <label className="sb-check">
        <input checked={primary} onChange={() => setPrimary((p) => !p)} type="checkbox" /> Đưa lên Quyết định ngay (đặt làm thẻ số 1 của sản phẩm)
      </label>
      <div className="sd-actions">
        {entries.length < 4 ? (
          <button className="sa-btn" data-testid="p2-add-more" onClick={onAdd} type="button">
            + Thêm phương án
          </button>
        ) : null}
        <button className="sa-btn" onClick={onBack} type="button">
          ‹ Tự tạo phương án
        </button>
      </div>
      {err ? (
        <p className="sd-error" role="alert">
          {err}
        </p>
      ) : null}
      {saved ? (
        <div className="sa-notice sa-notice--info" data-testid="p2-chosen" role="status">
          <b>
            Đã chuyển P{saved.index + 1} sang Quyết định · thẻ thủ công {saved.result.code ?? saved.result.id} · nguồn: thủ công
          </b>
          <br />
          Cửa sổ đo tự động 14 ngày (Đề xuất)
          {planHref ? (
            <>
              {" "}
              · kế hoạch thêm ở <NavLink className="sa-link" href={planHref}>Kế hoạch ›</NavLink>
            </>
          ) : null}
          {staffDraft || saved.result.status === "draft" ? " · Thẻ ở trạng thái nháp: Ops gửi cho shop trong danh sách đề xuất." : ""}
          {saved.ack ? <b className="sd-ack" data-testid="p2-ack"> {saved.ack}</b> : null}
        </div>
      ) : null}
      <p className="sa-hint">“Chọn” tạo thẻ thủ công trong Quyết định (mã JC, cửa sổ đo, kế hoạch). Juli không ghi gì lên Seller Centre: bạn tự lưu ở đó.</p>
      <BreachDialog
        busy={busy}
        closing="Bạn vẫn có thể chọn. Juli ghi lại rằng bạn đã xác nhận, kèm giờ, trên thẻ."
        lines={warn ? breachWarnLines(warn.breaches) : []}
        onBack={() => setWarn(null)}
        onGo={() => warn && void choose(warn.index, true, warn.breaches)}
        open={warn !== null}
        sheet={narrow}
        title={warn ? `Chọn P${warn.index + 1} dù chạm giá sàn?` : ""}
      />
    </section>
  );
}
