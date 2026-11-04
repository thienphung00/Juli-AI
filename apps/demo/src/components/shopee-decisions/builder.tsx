"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { ShopeeApiError } from "../../lib/shopee-analytics/client";
import { DASH, vnd } from "../../lib/shopee-analytics/format";
import {
  KINDS,
  MAX_ITEMS,
  MAX_VARIANTS,
  PCT_ONLY,
  compareBody,
  compareRows,
  defaultDiscount,
  discountLabel,
  discountRange,
  floorAlerts,
  floorLines,
  isCalc,
  kindName,
  orderLines,
  presetOf,
  sendable,
  toVariant,
  tradeoffs,
  type BuilderDiscount,
  type BuilderItem,
  type BuilderKind,
  type BuilderVariant,
  type CompareRow,
} from "../../lib/shopee-decisions/builder-model";
import { useReco, type ProductChoice } from "../../lib/shopee-decisions/context";
import type { Breach, CompareResult, ManualResult } from "../../lib/shopee-decisions/types";
import { MAX_TITLE_CHARS, ackText, breachWarnLines, breachesOf, titleCount } from "../../lib/shopee-decisions/versions";
import { useNarrow } from "../quyet-dinh/use-narrow";
import { Notice } from "../shopee-analytics/ui";
import { NavLink, errorText } from "./ui";
import { BreachDialog } from "./versions";

/**
 * Tự tạo phương án · So sánh phương án (artboards `TuTaoPhuongAn` and `TuTaoPhuongAnMobile`): the
 * person sets up to 4 offers, the server prices them side by side with the card builder
 * (`POST …/recommendations/compare`, nothing saved), and "Lưu thành đề xuất" saves the chosen one as a
 * manual card whose other variants are its versions (`POST …/recommendations/manual`). A floor or
 * spend-cap breach never blocks: it opens a warning and "Vẫn tiếp tục" is recorded.
 */

const BREACH_CODES = new Set(["reco_breach_unacknowledged", "reco_breach_not_acknowledged"]);

interface Saved {
  readonly code: string;
  readonly versions: number;
  readonly chosen: number;
  readonly promoted: boolean;
  readonly queueText: string;
  readonly ack: string | null;
  readonly draft: boolean;
}

type Cmp = { readonly status: "idle" } | { readonly status: "busy" } | { readonly status: "error"; readonly message: string } | { readonly status: "ready"; readonly result: CompareResult };
type Keyed = { readonly key: string; readonly state: Cmp };

const toneClass = (t: "up" | "down" | "flat"): string => (t === "up" ? "sa-tone--up" : t === "down" ? "sa-tone--down" : "");

export function BuilderView({ from, productId }: { readonly from: string | null; readonly productId: string | null }) {
  const host = useReco();
  const narrow = useNarrow();
  const [products, setProducts] = useState<readonly ProductChoice[]>([]);
  const [ready, setReady] = useState(!host.products);
  useEffect(() => {
    let live = true;
    host.products?.().then(
      (list) => {
        if (!live) return;
        setProducts(list);
        setReady(true);
      },
      () => live && setReady(true),
    );
    return () => {
      live = false;
    };
    // The list is per shop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [host.shopKey]);
  if (!ready) {
    return (
      <p className="sa-loading" role="status">
        Đang tải sản phẩm…
      </p>
    );
  }
  return <Builder from={from} narrow={narrow} productId={productId} products={products} />;
}

function Builder({ from, narrow, productId, products }: { readonly from: string | null; readonly narrow: boolean; readonly productId: string | null; readonly products: readonly ProductChoice[] }) {
  const host = useReco();
  const nameOf = (id: string): string => products.find((p) => p.id === id)?.name ?? id;
  const [vars, setVars] = useState<readonly BuilderVariant[]>(() => [presetOf("combo", products, productId)]);
  const [sel, setSel] = useState(0);
  const [choose, setChoose] = useState(0);
  const [promote, setPromote] = useState(false);
  const [keyed, setKeyed] = useState<Keyed | null>(null);
  const [warn, setWarn] = useState<{ readonly breaches: readonly Breach[] } | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState<Saved | null>(null);
  const cur = vars[sel] ?? vars[0]!;
  const sent = useMemo(() => sendable(vars), [vars]);
  const sentKey = JSON.stringify(sent.map((s) => [s.index, s.input]));
  const seq = useRef(0);

  // The answer belongs to the variants it was asked for; until it arrives for the current ones, it is "busy".
  const cmp: Cmp = sent.length === 0 ? { status: "idle" } : keyed?.key === sentKey ? keyed.state : { status: "busy" };
  useEffect(() => {
    if (sent.length === 0) return;
    const n = ++seq.current;
    const timer = window.setTimeout(() => {
      host.reco.compare(compareBody(sent)).then(
        (result) => n === seq.current && setKeyed({ key: sentKey, state: { status: "ready", result } }),
        (e: unknown) => n === seq.current && setKeyed({ key: sentKey, state: { status: "error", message: errorText(e) } }),
      );
    }, 350);
    return () => window.clearTimeout(timer);
    // `sentKey` says the variants changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sentKey, host.shopKey]);

  const update = (fn: (v: BuilderVariant) => BuilderVariant) => {
    setVars((all) => all.map((v, i) => (i === sel ? fn(v) : v)));
    setSaved(null);
  };
  const setItem = (slot: number, patch: Partial<BuilderItem>) =>
    update((v) => ({ ...v, items: v.items.map((it, i) => (i === slot ? { ...it, ...patch } : it)) }));

  const result = cmp.status === "ready" ? cmp.result : null;
  const rows: CompareRow[] = result ? compareRows(result, sent, vars.length) : [];
  const rowOf = (editor: number) => {
    const k = sent.findIndex((s) => s.index === editor);
    return k >= 0 ? result?.variants[k] : undefined;
  };
  const selRow = rowOf(sel);
  const chooseRow = rowOf(choose);
  const lines = orderLines(selRow, result?.today.margin_pct ?? null);
  const floors = floorLines(selRow, nameOf);
  const trade = result ? tradeoffs(result, sent) : [];
  const alerts = result ? floorAlerts(result, sent, nameOf) : [];
  const chooseBreaches = chooseRow?.card ? breachesOf(chooseRow.card) : [];
  const canSave = !!chooseRow?.ok && !!chooseRow.card && !saved && !host.readOnly;
  const nSent = sent.length;
  const listValue = null as number | null;
  const t = titleCount(cur.title);

  const back = from === "quyet-dinh" ? { href: host.href({}), label: "Quyết định" } : productId ? { href: host.links.product(productId, { tab: "dx" }), label: `Sản phẩm › ${nameOf(productId)} › Đề xuất` } : { href: host.href({}), label: "Quyết định" };

  const save = async (acknowledge: boolean) => {
    if (!chooseRow?.ok) return;
    const position = sent.findIndex((s) => s.index === choose);
    setSaving(true);
    setSaveError(null);
    try {
      let previousTop: string | null = null;
      const pid = chooseRow.card?.scope.product_ids[0] ?? null;
      if (promote && pid) {
        try {
          const before = await host.reco.list({ productId: pid, queue: "all" });
          previousTop = before.cards.find((c) => c.product_queue === 1)?.code ?? null;
        } catch {
          previousTop = null;
        }
      }
      const out: ManualResult = await host.reco.createManual({ variants: sent.map((s) => s.input), chosen: position, primary: promote, acknowledgeBreaches: acknowledge });
      let code = out.card.code ?? out.id;
      let queue = out.position;
      let total: number | null = null;
      try {
        const d = await host.reco.detail(out.id);
        code = d.code ?? code;
        queue = d.product_queue ?? queue;
        if (pid) total = (await host.reco.list({ productId: pid, queue: "all" })).cards.filter((c) => c.product_queue !== null && c.product_queue !== undefined).length;
      } catch {
        /* the card is saved; the code falls back to its id */
      }
      setWarn(null);
      setSaved({
        code,
        versions: out.versions.length,
        chosen: position + 1,
        promoted: promote,
        draft: out.status === "draft",
        ack: acknowledge && chooseBreaches.length > 0 ? ackText(chooseBreaches, new Date().toISOString()) : null,
        queueText: promote
          ? `Đã đưa lên Quyết định: ${code} là thẻ số 1 của sản phẩm${previousTop ? `, ${previousTop} xuống số 2` : ""}.`
          : `Thẻ vào hàng đợi của sản phẩm theo điểm (#${queue}${total ? ` trong ${total} thẻ` : ""}), chưa lên Quyết định. Bạn có thể đưa lên sau.`,
      });
    } catch (e) {
      if (e instanceof ShopeeApiError && BREACH_CODES.has(e.code) && Array.isArray(e.detail?.["breaches"])) setWarn({ breaches: e.detail["breaches"] as Breach[] });
      else setSaveError(errorText(e));
    } finally {
      setSaving(false);
    }
  };
  const onSave = () => (chooseBreaches.length > 0 ? setWarn({ breaches: chooseBreaches }) : void save(false));

  const addVariant = () => {
    setVars((all) => [...all, cur]);
    setSel(vars.length);
    setSaved(null);
  };

  return (
    <div className="sa-page sb" data-testid="sb-page">
      <header className="sa-prodhead">
        <NavLink className="sa-link" href={back.href}>
          ‹ {back.label}
        </NavLink>
        {narrow ? null : <div className="sa-eyebrow">TỰ TẠO PHƯƠNG ÁN · SO SÁNH PHƯƠNG ÁN</div>}
        {narrow || !host.shopName ? null : <span className="sa-chip sa-chip--outline sa-row__end">Shopee · {host.shopName}</span>}
      </header>
      <div>
        {narrow ? <div className="sa-eyebrow">TỰ TẠO PHƯƠNG ÁN</div> : null}
        <h1 className="sa-h1">Tự đặt ưu đãi, xem số trước khi quyết định</h1>
        <p className="sa-hint">
          {narrow
            ? "Thêm tối đa 4 phương án rồi so sánh. Chưa lưu gì cho đến khi bấm “Lưu thành đề xuất”."
            : "Nhập thay đổi bạn muốn thử, thêm tối đa 4 phương án để đặt cạnh nhau. Chưa lưu gì cho đến khi bấm “Lưu thành đề xuất”. Số tính bằng cùng công thức với thẻ Juli đề xuất."}
        </p>
      </div>

      <div className="sb-grid">
        <section className="sa-card sb-editor" data-testid="sb-editor">
          <div className="sb-tabs">
            {vars.map((_, i) => (
              <button aria-pressed={i === sel} className={`sa-seg__item sb-pill ${i === sel ? "sb-pill--on" : ""}`} key={i} onClick={() => setSel(i)} type="button">
                P{i + 1}
              </button>
            ))}
            {vars.length < MAX_VARIANTS && isCalc(cur.kind) ? (
              <button className="sa-btn sa-btn--s" onClick={addVariant} type="button">
                {narrow ? "+ Thêm" : "+ Thêm phương án"}
              </button>
            ) : null}
            <span className="sa-hint" data-testid="sb-count">
              {vars.length}/{MAX_VARIANTS}
            </span>
          </div>

          <div className="sb-field">
            <span className="sd-field__label">Loại thay đổi</span>
            <div className="sb-chips">
              {KINDS.map(([k, label]) => (
                <button aria-pressed={cur.kind === k} className={`sb-pill ${cur.kind === k ? "sb-pill--dark" : ""}`} key={k} onClick={() => update((v) => presetOf(k as BuilderKind, products, productId, v))} type="button">
                  {label}
                </button>
              ))}
            </div>
          </div>

          {isCalc(cur.kind) ? (
            <>
              <div className="sb-field">
                <span className="sd-field__label">{narrow ? "Sản phẩm (tối đa 3 khác nhau)" : "Sản phẩm trong phương án (tối đa 3 sản phẩm khác nhau)"}</span>
                {cur.items.slice(0, MAX_ITEMS).map((it, i) => (
                  <ItemRow choices={products} item={it} key={i} n={i + 1} onId={(id) => setItem(i, { id, qty: id ? Math.max(it.qty, 1) : 0 })} onQty={(qty) => setItem(i, { qty, ...(qty === 0 ? { id: "" } : {}) })} />
                ))}
              </div>

              <div className="sb-field">
                <span className="sd-field__label">Cách giảm giá</span>
                <div className="sa-seg sa-seg--round">
                  {(
                    [
                      ["pct", "%"],
                      ["amt", "Số tiền (đ)"],
                      ["price", "Giá combo cố định"],
                    ] as const
                  )
                    .filter(([k]) => !PCT_ONLY.has(cur.kind) || k === "pct")
                    .map(([k, label]) => (
                      <button aria-pressed={cur.dtype === k} className={`sa-seg__item ${cur.dtype === k ? "sa-seg__item--on" : ""}`} key={k} onClick={() => update((v) => ({ ...v, dtype: k as BuilderDiscount, dval: defaultDiscount(k as BuilderDiscount, listValue) }))} type="button">
                        {label}
                      </button>
                    ))}
                </div>
                <b className="sd-field__value" data-testid="sb-dlabel">
                  {discountLabel(cur.dtype, cur.dval)}
                </b>
                <input
                  aria-label="Mức giảm"
                  max={discountRange(cur.dtype).max}
                  min={discountRange(cur.dtype).min}
                  onChange={(e) => update((v) => ({ ...v, dval: Number(e.target.value) }))}
                  step={discountRange(cur.dtype).step}
                  type="range"
                  value={cur.dval}
                />
                {cur.dtype !== "pct" ? (
                  <input aria-label="Mức giảm (đ)" className="sb-num" min={0} onChange={(e) => update((v) => ({ ...v, dval: Math.max(0, Number(e.target.value) || 0) }))} type="number" value={cur.dval} />
                ) : null}
                <span className="sa-hint">{cur.dtype === "price" ? "Giá cố định thấp hơn giá niêm yết cả giỏ thì giảm sâu hơn." : cur.dtype === "pct" ? "Giảm trên tổng giá niêm yết của giỏ." : "Trừ thẳng số tiền này khỏi giỏ."}</span>
              </div>

              {cur.kind !== "voucher" ? (
                <div className="sb-field">
                  <label className="sb-check">
                    <input checked={!!cur.voucher} onChange={() => update((v) => ({ ...v, voucher: v.voucher ? null : { v: 10000, min: 200000 } }))} type="checkbox" /> Cộng thêm voucher
                  </label>
                  {cur.voucher ? <VoucherSliders onChange={(voucher) => update((v) => ({ ...v, voucher }))} voucher={cur.voucher} /> : null}
                </div>
              ) : (
                <div className="sb-field">
                  <VoucherSliders onChange={(voucher) => update((v) => ({ ...v, voucher }))} voucher={cur.voucher ?? { v: 15000, min: 150000 }} />
                </div>
              )}

              {cur.kind !== "voucher" && cur.kind !== "disc" ? (
                <div className="sb-field">
                  <span className="sd-field__label">{narrow ? "Quà tặng kèm" : "Quà tặng kèm (tính giá vốn + đóng gói)"}</span>
                  <div className="sb-chips">
                    {[{ id: "", name: "Không tặng" }, ...products].map((p) => (
                      <button aria-pressed={(cur.gift ?? "") === p.id} className={`sb-pill ${(cur.gift ?? "") === p.id ? "sb-pill--on" : ""}`} key={p.id || "none"} onClick={() => update((v) => ({ ...v, gift: p.id || null }))} type="button">
                        {p.name}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          ) : null}

          {cur.kind === "ads" ? (
            <div className="sb-field" data-testid="sb-ads">
              <b>Quảng cáo</b>
              {narrow ? " so sánh theo phiên bản trong thẻ, chưa có bảng chung. " : ": chọn chiến dịch và đổi ngân sách ±%. Loại này so sánh theo phiên bản ngay trong thẻ (−20% / +20% / +50%), chưa có bảng tính chung với combo, nên chưa thêm vào bảng bên phải. "}
              <NavLink className="sa-link" href={productId ? host.links.product(productId, { tab: "dx" }) : host.href({})}>
                Mở thẻ quảng cáo ›
              </NavLink>
            </div>
          ) : null}
          {cur.kind === "title" ? (
            <div className="sb-field" data-testid="sb-title">
              <label className="sd-field__label" htmlFor="sb-title-box">
                Tiêu đề (tối đa {MAX_TITLE_CHARS} ký tự)
              </label>
              <textarea aria-describedby="sb-title-count" className={`sv-title__box ${t.over ? "sv-title__box--over" : ""}`} id="sb-title-box" onChange={(e) => update((v) => ({ ...v, title: e.target.value }))} rows={narrow ? 4 : 3} value={cur.title} />
              <div className="sv-title__meta">
                <span className={`sa-chip sa-chip--${t.tone === "up" ? "up" : t.tone === "warn" ? "warn" : "down"}`} id="sb-title-count">
                  {t.n}/{MAX_TITLE_CHARS}
                </span>
                <span className={t.over ? "sv-title__over" : "sa-hint"}>{t.over ? `Quá ${t.n - MAX_TITLE_CHARS} ký tự: không lưu được.` : `Còn ${MAX_TITLE_CHARS - t.n} ký tự.`}</span>
              </div>
              {narrow ? null : <span className="sa-hint">Tiêu đề so sánh theo phiên bản trong thẻ tiêu đề; ở đây chỉ nhập và kiểm giới hạn. Trên 100 ký tự: không lưu được.</span>}
            </div>
          ) : null}
        </section>

        <div className="sb-right">
          <section className="sa-card" data-testid="sb-compare">
            <div className="sa-card__head">
              <h2 className="sa-h2">So sánh phương án</h2>
              <span className="sa-hint">{narrow ? "Vuốt ngang để xem từng phương án." : "30 ngày, dự kiến. Mỗi ô: giá trị, chênh lệch so với hôm nay, và so với P1 (phương án gốc)."}</span>
            </div>
            {cmp.status === "busy" ? (
              <p className="sa-hint" role="status">
                Đang tính…
              </p>
            ) : null}
            {cmp.status === "error" ? (
              <p className="sd-error" role="alert">
                {cmp.message}
              </p>
            ) : null}
            {sent.length === 0 ? <p className="sa-hint">{vars.length > 0 && !isCalc(cur.kind) ? "Loại này chưa có bảng tính ở đây." : (toVariant(cur).problem ?? "Chọn sản phẩm để tính.")}</p> : null}
            {sent.length > 0 && cmp.status !== "ready" ? sent.map((s) => toVariant(vars[s.index]!).problem).filter(Boolean).map((p, i) => <p className="sa-hint" key={i}>{p}</p>) : null}
            {result ? (
              narrow ? (
                <SwipeCards nameOf={nameOf} onPick={setSel} rows={rows} sel={sel} vars={vars} />
              ) : (
                <CompareTable nameOf={nameOf} rows={rows} sel={sel} vars={vars} />
              )
            ) : null}
            {result
              ? sent.map((s, k) => {
                  const r = result.variants[k];
                  return r && !r.ok ? (
                    <p className="sd-error" key={s.index} role="alert">
                      P{s.index + 1}: {r.refusal?.message ?? "Chưa tính được."}
                    </p>
                  ) : null;
                })
              : null}
            {trade.map((x, i) => (
              <div className="sb-trade" key={i}>
                <b>Đánh đổi:</b> {x}
              </div>
            ))}
            {alerts.map((a, i) => (
              <div className="sd-check sd-check--bad" key={i} role="alert">
                <span>
                  <b>{a.title}</b> {a.text}
                </span>
              </div>
            ))}
          </section>

          <section className="sa-card" data-testid="sb-order">
            <h3 className="sa-h2">Một đơn của {selRow?.ok ? `P${sel + 1}` : "phương án đang chọn"}</h3>
            {lines ? (
              <div className="sb-order">
                {lines.map((l) => (
                  <div key={l.k}>
                    <span>{l.k}</span>
                    <b className={l.tone ? toneClass(l.tone) : ""}>{l.v}</b>
                  </div>
                ))}
              </div>
            ) : (
              <p className="sa-hint">Loại này chưa có bảng tính.</p>
            )}
            {floors.length > 0 ? (
              <div className="sb-floors">
                <b>{narrow ? "Giá sàn từng sản phẩm" : "Giá sàn theo từng sản phẩm trong phương án (phần tiền khách trả chia theo giá niêm yết)"}</b>
                {floors.map((f) => (
                  <div className={f.bad ? "sb-floor sb-floor--bad" : "sb-floor"} key={f.name}>
                    <span>{f.name}</span>
                    <span>{f.text}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </section>

          <section className="sa-card" data-testid="sb-save">
            <h3 className="sa-h2">Lưu thành đề xuất</h3>
            <div className="sb-tabs" role="radiogroup" aria-label="Phương án được chọn">
              <span className="sa-hint">{narrow ? "Chọn:" : "Phương án được chọn:"}</span>
              {vars.map((_, i) => {
                const r = rowOf(i);
                const bad = !!r?.card && breachesOf(r.card).length > 0;
                const off = !r?.ok;
                return (
                  <button aria-checked={choose === i} className={`sb-pill ${choose === i ? "sb-pill--on" : ""}`} disabled={off} key={i} onClick={() => setChoose(i)} role="radio" type="button">
                    P{i + 1}
                    {bad ? " (chạm giá sàn)" : off ? " (không lưu ở đây)" : ""}
                  </button>
                );
              })}
            </div>
            <label className="sb-check">
              <input checked={promote} onChange={() => setPromote((p) => !p)} type="checkbox" /> {narrow ? "Đưa lên Quyết định ngay (thẻ số 1 của sản phẩm)" : "Đưa lên Quyết định ngay (đặt làm thẻ số 1 của sản phẩm; thẻ hiện tại xuống số 2)"}
            </label>
            <div className="sd-actions">
              <button className="sa-btn sa-btn--primary" data-testid="sb-save-btn" disabled={!canSave || saving || (cur.kind === "title" && t.over)} onClick={onSave} type="button">
                Lưu thành đề xuất
              </button>
              {saved ? null : (
                <span className={`sa-hint ${chooseBreaches.length > 0 ? "sd-hint--warn" : ""}`} data-testid="sb-save-hint">
                  {chooseBreaches.length > 0 ? `P${choose + 1} chạm giá sàn: vẫn lưu được, Juli hiện cảnh báo trước.` : !chooseRow?.ok ? "Phương án này chưa lưu được ở đây." : nSent > 1 ? `Lưu ${nSent} phương án thành các phiên bản của một thẻ, phiên bản chọn là V1.` : "Lưu một phương án thành thẻ."}
                </span>
              )}
            </div>
            {saveError ? (
              <p className="sd-error" role="alert">
                {saveError}
              </p>
            ) : null}
            {saved ? (
              <Notice tone="info" testId="sb-saved">
                <b>Đã lưu {saved.code}</b> · {narrow ? "thủ công" : "nguồn: thủ công"} · {saved.versions} phiên bản ({saved.code}-V1{saved.versions > 1 ? ` … -V${saved.versions}` : ""}), mở bằng V1.{" "}
                <span data-testid="sb-saved-queue">{saved.queueText}</span>
                {saved.draft ? " Thẻ ở trạng thái nháp: Ops gửi cho shop trong danh sách đề xuất." : ""}
                {saved.ack ? <b className="sd-ack"> {saved.ack}</b> : null}
                {narrow ? null : " Người tạo được ghi cùng thẻ. Thẻ thủ công được duyệt, thực hiện và đo như thẻ Juli đề xuất, nhưng kết quả được tính riêng khi Juli học."}
              </Notice>
            ) : null}
          </section>
        </div>
      </div>

      <BreachDialog
        busy={saving}
        closing="Bạn vẫn có thể lưu. Juli ghi lại rằng bạn đã xác nhận, kèm giờ, trên thẻ."
        lines={warn ? breachWarnLines(warn.breaches) : []}
        onBack={() => setWarn(null)}
        onGo={() => void save(true)}
        open={warn !== null}
        sheet={narrow}
        title={`Lưu P${choose + 1} dù chạm giá sàn?`}
      />
    </div>
  );
}

function ItemRow({ n, item, choices, onId, onQty }: { readonly n: number; readonly item: BuilderItem; readonly choices: readonly ProductChoice[]; readonly onId: (id: string) => void; readonly onQty: (qty: number) => void }) {
  const many = choices.length > 6;
  return (
    <div className="sb-item" data-testid={`sb-item-${n}`}>
      <span className="sb-item__n">{n}</span>
      {many ? (
        <select aria-label={`Sản phẩm ${n}`} onChange={(e) => onId(e.target.value)} value={item.id}>
          <option value="">—</option>
          {choices.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      ) : (
        <span className="sb-chips">
          {[{ id: "", name: "—" }, ...choices].map((p) => (
            <button aria-pressed={item.id === p.id} className={`sb-pill ${item.id === p.id ? "sb-pill--on" : ""}`} key={p.id || "none"} onClick={() => onId(p.id)} type="button">
              {p.name}
            </button>
          ))}
        </span>
      )}
      <span className="sd-stepper">
        <button aria-label="Giảm số lượng" onClick={() => onQty(Math.max(0, item.qty - 1))} type="button">
          −
        </button>
        <b>{item.qty}</b>
        <button aria-label="Tăng số lượng" disabled={!item.id} onClick={() => onQty(Math.min(9, item.qty + 1))} type="button">
          +
        </button>
      </span>
    </div>
  );
}

function VoucherSliders({ voucher, onChange }: { readonly voucher: { readonly v: number; readonly min: number }; readonly onChange: (v: { readonly v: number; readonly min: number }) => void }) {
  return (
    <div className="sb-voucher">
      <b>
        {vnd(voucher.v)} cho đơn ≥ {vnd(voucher.min)}
      </b>
      <input aria-label="Giá trị voucher" max={30000} min={5000} onChange={(e) => onChange({ ...voucher, v: Number(e.target.value) })} step={1000} type="range" value={voucher.v} />
      <input aria-label="Đơn tối thiểu của voucher" max={300000} min={150000} onChange={(e) => onChange({ ...voucher, min: Number(e.target.value) })} step={1000} type="range" value={voucher.min} />
      <span className="sa-hint">Voucher dùng quy tắc đơn tối thiểu hiện có của shop.</span>
    </div>
  );
}

function headOf(v: BuilderVariant, i: number, nameOf: (id: string) => string): { readonly label: string; readonly sub: string } {
  return { label: `P${i + 1} · ${kindName(v.kind)}`, sub: isCalc(v.kind) ? `${v.items.filter((x) => x.id && x.qty > 0).map((x) => `${x.qty}× ${nameOf(x.id).split(" ").slice(-1)[0]}`).join(" + ")} · ${v.dtype === "pct" ? `${v.dval}%` : v.dtype === "amt" ? `−${vnd(v.dval)}` : `giá ${vnd(v.dval)}`}${v.voucher ? ` + voucher ${vnd(v.voucher.v)}` : ""}${v.gift ? " + quà" : ""}` : kindName(v.kind) };
}

function CompareTable({ rows, vars, sel, nameOf }: { readonly rows: readonly CompareRow[]; readonly vars: readonly BuilderVariant[]; readonly sel: number; readonly nameOf: (id: string) => string }) {
  const style = { ["--sv-cols" as string]: vars.length } as React.CSSProperties;
  return (
    <div className="sv-scroll">
      <div className="sv-grid sb-table" data-testid="sb-table" style={style}>
        <div className="sv-head sv-head--label">
          <b>Chỉ số</b>
        </div>
        <div className="sv-head sv-head--today">
          <b>Hôm nay</b>
          <span>chưa có phương án</span>
        </div>
        {vars.map((v, i) => (
          <div className={`sv-head ${i === sel ? "sv-head--on" : ""}`} key={i}>
            <b>{headOf(v, i, nameOf).label}</b>
            <span>{headOf(v, i, nameOf).sub}</span>
          </div>
        ))}
        {rows.map((r) => (
          <RowCells key={r.key} row={r} sel={sel} vars={vars} />
        ))}
      </div>
    </div>
  );
}

function RowCells({ row, vars, sel }: { readonly row: CompareRow; readonly vars: readonly BuilderVariant[]; readonly sel: number }) {
  return (
    <>
      <div className="sv-cell sv-cell--label" data-testid={`sb-row-${row.key}`}>
        <b>{row.label}</b>
        <span>{row.sub}</span>
      </div>
      <div className="sv-cell sv-cell--today">
        <span className="sd-muted">{row.today}</span>
      </div>
      {row.cells.map((c, i) =>
        c ? (
          <div className={`sv-cell ${i === sel ? "sv-cell--sel" : ""} ${row.key === "floor" && c.tone === "down" ? "sv-cell--bad" : ""}`} data-testid={`sb-${row.key}-${i + 1}`} key={i}>
            <span className={`sv-cell__v ${row.key === "floor" ? `sv-cell__v--s ${toneClass(c.tone)}` : ""}`}>{c.v}</span>
            {c.d && row.key !== "floor" ? <span className={`sv-cell__d sv-cell__d--${c.tone}`}>{c.d}</span> : null}
            {c.vs ? <span className="sv-cell__vs">{c.vs}</span> : null}
          </div>
        ) : (
          <div className="sv-cell" key={i}>
            <span className="sv-cell__v sd-muted">{DASH}</span>
            <span className="sv-cell__vs">{vars[i] && !isCalc(vars[i]!.kind) ? "so sánh trong thẻ" : ""}</span>
          </div>
        ),
      )}
    </>
  );
}

function SwipeCards({ rows, vars, sel, onPick, nameOf }: { readonly rows: readonly CompareRow[]; readonly vars: readonly BuilderVariant[]; readonly sel: number; readonly onPick: (i: number) => void; readonly nameOf: (id: string) => string }) {
  return (
    <div className="sb-swipe" data-testid="sb-swipe">
      {vars.map((v, i) => (
        <div className={`sb-swipe__card ${i === sel ? "sb-swipe__card--on" : ""}`} key={i}>
          <button className="sb-swipe__head" onClick={() => onPick(i)} type="button">
            <b>P{i + 1}</b>
            <span>{headOf(v, i, nameOf).label.split(" · ")[1]} · {headOf(v, i, nameOf).sub}</span>
          </button>
          {rows.map((r) => {
            const c = r.cells[i];
            return (
              <div className="sb-swipe__row" key={r.key}>
                <span>{r.label}</span>
                <span className="sv-cell__v">{c ? c.v : DASH}</span>
                {c?.d && r.key !== "floor" ? <span className={`sv-cell__d sv-cell__d--${c.tone}`}>{c.d}</span> : null}
                {c?.vs ? <span className="sv-cell__vs">{c.vs}</span> : null}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

