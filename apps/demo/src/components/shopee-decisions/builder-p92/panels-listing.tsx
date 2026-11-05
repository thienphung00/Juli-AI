"use client";

import { useEffect, useState } from "react";

import { fmt, vnd } from "../../../lib/shopee-analytics/format";
import type { AdsCampaigns, CoverOverlay, KeywordTable } from "../../../lib/shopee-decisions/builder-api";
import { MAX_FIRST_LINE, MAX_TITLE, type Forms } from "../../../lib/shopee-decisions/builder-p92";
import { LlmOff, NumIn, Pills, Seg, TextIn, setAt, useDraft, type PanelCtx } from "./shared";

/**
 * Input panels of the listing and marketing strategies: Quảng cáo (4 levers), Tiêu đề (keyword table -> LLM
 * drafts, free edit with counter and coverage), Ảnh bìa (overlay concepts as text over the real photo; the photo
 * is never altered and nothing is generated), Mô tả, Affiliate / KOL, Hiển thị giá + listing.
 */

type P<K extends keyof Forms> = { readonly form: Forms[K]; readonly set: (patch: Partial<Forms[K]>) => void; readonly ctx: PanelCtx };

const chars = (s: string): number => [...s].length;

// ── Quảng cáo ────────────────────────────────────────────────────────────

export function AdsPanel({ form, set, ctx }: P<"ads">) {
  const [data, setData] = useState<AdsCampaigns | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    ctx.api.adsCampaigns().then(
      (r) => live && setData(r),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
    // The campaigns are per shop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const camp = data?.campaigns.find((c) => c.campaign_key === form.campaignKey);
  const kws = form.keywords;
  return (
    <div className="p2-panel" data-testid="p2-panel-ads">
      <Pills
        label="Đòn bẩy"
        onChange={(lever) => set({ lever })}
        options={[
          ["budget", "① Ngân sách mỗi ngày"],
          ["roas", "② ROAS mục tiêu"],
          ["add_product", "③ Thêm sản phẩm"],
          ["remove_product", "③ Bỏ sản phẩm"],
          ["keywords", "④ Từ khoá và giá thầu"],
        ]}
        value={form.lever}
      />
      {failed ? <p className="sd-error">Chưa tải được chiến dịch quảng cáo.</p> : null}
      {form.lever !== "keywords" ? (
        <label className="p2-field">
          <span className="sd-field__label">Chiến dịch</span>
          <select aria-label="Chiến dịch" className="p2-select" onChange={(e) => set({ campaignKey: e.target.value })} value={form.campaignKey}>
            <option value="">—</option>
            {(data?.campaigns ?? []).map((c) => (
              <option key={c.campaign_key} value={c.campaign_key}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {form.lever === "budget" ? <NumIn hint={camp ? `Hôm nay ${vnd(camp.daily_budget)}/ngày` : undefined} label="Ngân sách mới mỗi ngày" onChange={(dailyBudget) => set({ dailyBudget })} suffix="đ/ngày" value={form.dailyBudget} /> : null}
      {form.lever === "roas" ? <NumIn hint={camp ? `Hôm nay ${camp.roas_target ?? "—"} · ROAS hoà vốn ${camp.break_even_roas ?? "—"}` : undefined} label="ROAS mục tiêu mới" onChange={(roasTarget) => set({ roasTarget })} value={form.roasTarget} /> : null}
      {form.lever === "add_product" || form.lever === "remove_product" ? (
        <div className="p2-field">
          <span className="sd-field__label">Sản phẩm</span>
          <select aria-label="Sản phẩm trong chiến dịch" className="p2-select" onChange={(e) => set({ itemId: e.target.value })} value={form.itemId || ctx.product.item_id}>
            {form.lever === "remove_product" && camp ? camp.products.map((p) => <option key={p.item_id} value={p.item_id}>{p.name}</option>) : ctx.products.map((p) => <option key={p.item_id} value={p.item_id}>{p.name}</option>)}
          </select>
        </div>
      ) : null}
      {camp && camp.products.length > 0 ? (
        <table className="p2-table" data-testid="p2-ads-products">
          <thead>
            <tr>
              <th>Sản phẩm</th>
              <th>ROAS hoà vốn</th>
              <th>ROAS thực tế</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {camp.products.map((p) => (
              <tr key={p.item_id}>
                <td>{p.name}</td>
                <td>{p.break_even_roas === null ? "—" : fmt(p.break_even_roas, 1)}</td>
                <td>{p.roas_direct === null ? "—" : fmt(p.roas_direct, 1)}</td>
                <td>{p.below_break_even ? "Dưới hoà vốn" : "Giữ"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {form.lever === "keywords" ? (
        <div className="p2-rows">
          {kws.map((k, i) => (
            <div className="p2-row p2-row--wrap" key={i}>
              <TextIn label={`Từ khoá ${i + 1}`} onChange={(keyword) => set({ keywords: setAt(kws, i, { keyword }) })} value={k.keyword} />
              <NumIn label={`Giá thầu ${i + 1}`} onChange={(bid) => set({ keywords: setAt(kws, i, { bid }) })} suffix="đ" value={k.bid} />
              <Seg label={`Kiểu khớp ${i + 1}`} onChange={(match) => set({ keywords: setAt(kws, i, { match }) })} options={[["broad", "Rộng"], ["exact", "Chính xác"]]} value={k.match} />
              {kws.length > 1 ? (
                <button aria-label={`Bỏ từ khoá ${i + 1}`} className="sa-btn sa-btn--s" onClick={() => set({ keywords: kws.filter((_, n) => n !== i) })} type="button">
                  ×
                </button>
              ) : null}
            </div>
          ))}
          <button className="sa-btn sa-btn--s" onClick={() => set({ keywords: [...kws, { keyword: "", bid: "", match: "broad" }] })} type="button">
            + Thêm từ khoá
          </button>
          {(Array.isArray(ctx.outcome?.details?.["keywords"]) ? (ctx.outcome!.details!["keywords"] as Readonly<Record<string, unknown>>[]) : []).map((k, i) => (
            <span className="sa-hint" key={i}>
              {String(k["keyword"])}: {typeof k["volume"] === "number" ? `${fmt(k["volume"] as number)} lượt tìm/tháng` : "chưa có lượt tìm"}
              {k["bid_below_cpc_min"] === true ? " · giá thầu thấp hơn CPC tối thiểu" : ""}
            </span>
          ))}
        </div>
      ) : null}
      {data?.daily_cap ? <p className="sa-hint">Trần chi marketing mỗi ngày của shop: {vnd(data.daily_cap)} (Cài đặt › Mục tiêu). Vượt trần chỉ cảnh báo.</p> : null}
    </div>
  );
}

// ── Tiêu đề ──────────────────────────────────────────────────────────────

export function coverage(text: string, ticked: readonly string[]): { readonly covered: readonly string[]; readonly missing: readonly string[] } {
  const low = text.toLowerCase();
  return { covered: ticked.filter((k) => low.includes(k.toLowerCase())), missing: ticked.filter((k) => !low.includes(k.toLowerCase())) };
}

export function TitlePanel({ form, set, ctx }: P<"title">) {
  const [table, setTable] = useState<KeywordTable | null>(null);
  const [tableErr, setTableErr] = useState(false);
  useEffect(() => {
    let live = true;
    ctx.api.keywords(ctx.product.item_id).then(
      (r) => live && setTable(r),
      () => live && setTableErr(true),
    );
    return () => {
      live = false;
    };
    // One keyword table per product.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx.product.item_id]);
  const [draft, run] = useDraft(() => ctx.api.draftTitle({ itemId: ctx.product.item_id, keywords: form.ticked, count: 3 }));
  const n = chars(form.text);
  const cov = coverage(form.text, form.ticked);
  const toggle = (k: string) => set({ ticked: form.ticked.includes(k) ? form.ticked.filter((x) => x !== k) : [...form.ticked, k].slice(0, 12) });
  const missingSources = (table?.sources ?? []).filter((s) => !s.present && s.reason);
  return (
    <div className="p2-panel" data-testid="p2-panel-title">
      {tableErr ? <p className="sd-error">Chưa tải được bảng từ khoá.</p> : null}
      {table?.title ? (
        <p className="sa-hint" data-testid="p2-current-title">
          Tiêu đề hiện tại ({table.title_chars}/{table.max_title_chars}): {table.title}
        </p>
      ) : null}
      {table ? (
        <table className="p2-table" data-testid="p2-kw-table">
          <thead>
            <tr>
              <th />
              <th>Từ khoá</th>
              <th>Nguồn</th>
              <th>Lượt tìm</th>
              <th>Độ khó</th>
              <th>Trong tiêu đề</th>
            </tr>
          </thead>
          <tbody>
            {table.keywords.map((k) => (
              <tr key={k.keyword}>
                <td>
                  <input aria-label={`Chọn từ khoá ${k.keyword}`} checked={form.ticked.includes(k.keyword)} onChange={() => toggle(k.keyword)} type="checkbox" />
                </td>
                <td>{k.keyword}</td>
                <td>{k.sources.map((s) => ({ title: "trong tiêu đề", suggestion: "gợi ý tìm kiếm", competitor: "tiêu đề đối thủ", ads: "báo cáo từ khoá QC" })[s] ?? s).join(", ")}</td>
                <td>{k.volume === null ? "chưa tra" : fmt(k.volume)}</td>
                <td>{k.difficulty === null ? "—" : fmt(k.difficulty)}</td>
                <td>{k.in_title ? "có" : "chưa"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {missingSources.map((s) => (
        <p className="sa-hint" key={s.key}>
          {s.label}: {s.reason}
        </p>
      ))}
      <div className="sd-actions">
        <button className="sa-btn sa-btn--primary" data-testid="p2-title-draft" disabled={form.ticked.length === 0 || draft.status === "busy"} onClick={run} type="button">
          Viết 3 tiêu đề bằng từ khoá đã chọn
        </button>
        {form.ticked.length === 0 ? <span className="sa-hint">Tick ít nhất một từ khoá.</span> : null}
      </div>
      {draft.status === "busy" ? (
        <p className="sa-hint" role="status">
          Đang viết…
        </p>
      ) : null}
      {draft.status === "off" ? <LlmOff message={draft.message} /> : null}
      {draft.status === "error" ? (
        <p className="sd-error" role="alert">
          {draft.message}
        </p>
      ) : null}
      {draft.status === "ready" ? (
        <ul className="p2-drafts" data-testid="p2-title-drafts">
          {draft.data.drafts.map((d, i) => (
            <li key={i}>
              <span>{d.title}</span>
              <span className="sa-hint">
                {d.chars}/{draft.data.max_chars} · phủ {d.keywords?.covered.length ?? 0}/{form.ticked.length} từ khoá đã chọn
              </span>
              <button className="sa-btn sa-btn--s" onClick={() => set({ text: d.title })} type="button">
                Dùng
              </button>
            </li>
          ))}
          {draft.data.drafts.length === 0 ? <li className="sa-hint">Không có bản nháp nào đạt kiểm tra.</li> : null}
        </ul>
      ) : null}
      <label className="p2-field p2-field--wide">
        <span className="sd-field__label">Sửa tự do · tiêu đề (tối đa {MAX_TITLE} ký tự)</span>
        <textarea aria-label="Tiêu đề" className={`sv-title__box ${n > MAX_TITLE ? "sv-title__box--over" : ""}`} onChange={(e) => set({ text: e.target.value })} rows={3} value={form.text} />
      </label>
      <div className="sv-title__meta">
        <span className={`sa-chip sa-chip--${n > MAX_TITLE ? "down" : "up"}`} data-testid="p2-title-count">
          {n}/{MAX_TITLE}
        </span>
        {form.ticked.map((k) => (
          <span className="sa-hint" key={k}>
            {cov.covered.includes(k) ? "✓" : "✕"} {k}
          </span>
        ))}
      </div>
      {n > MAX_TITLE ? <p className="sv-title__over">Quá {n - MAX_TITLE} ký tự: không thêm được.</p> : null}
      <p className="sa-hint">Điền bằng Connector có ở bước thực hiện, sau khi bạn chọn phương án và duyệt thẻ: Juli điền tiêu đề đã chọn lên Seller Centre, bạn kiểm tra và lưu. Tiêu đề chỉ dùng thông tin shop đã nhập; không thêm chứng nhận hay thành phần shop chưa cung cấp.</p>
    </div>
  );
}

// ── Ảnh bìa ──────────────────────────────────────────────────────────────

export function overlayLines(o: CoverOverlay): string[] {
  const out: string[] = [];
  if (o.price_vnd) out.push(vnd(o.price_vnd));
  if (o.original_price_vnd) out.push(`${vnd(o.original_price_vnd)} (giá gốc)`);
  if (o.discount_pct) out.push(`−${fmt(o.discount_pct, 0)}%`);
  if (o.badge_text) out.push(o.badge_text);
  if (o.voucher_text) out.push(o.voucher_text);
  if (o.pack_text) out.push(o.pack_text);
  if (o.hook_text) out.push(o.hook_text);
  return out;
}

export function CoverPreview({ overlay }: { readonly overlay: CoverOverlay }) {
  return (
    <div className={`p2-cover p2-cover--${overlay.layout}`} data-testid="p2-cover-preview">
      <span className="p2-cover__photo">ảnh thật, giữ nguyên</span>
      <span className="p2-cover__text">
        {overlayLines(overlay).map((l, i) => (
          <b key={i}>{l}</b>
        ))}
      </span>
    </div>
  );
}

const LAYOUTS = [
  ["banner_top", "Băng trên"],
  ["banner_bottom", "Băng dưới"],
  ["corner_tag", "Nhãn góc"],
] as const;

export function CoverPanel({ form, set, ctx }: P<"cover_image">) {
  const [draft, run] = useDraft(() => ctx.api.draftCover({ itemId: ctx.product.item_id, count: 3 }));
  const o = form.overlay;
  const edit = (patch: Partial<CoverOverlay>) => o && set({ overlay: { ...o, ...patch } });
  return (
    <div className="p2-panel" data-testid="p2-panel-cover">
      <div className="sd-actions">
        <button className="sa-btn sa-btn--primary" data-testid="p2-cover-draft" disabled={draft.status === "busy"} onClick={run} type="button">
          Đề xuất lớp chữ từ số của sản phẩm
        </button>
      </div>
      {draft.status === "busy" ? (
        <p className="sa-hint" role="status">
          Đang đề xuất…
        </p>
      ) : null}
      {draft.status === "off" ? <LlmOff message={draft.message} /> : null}
      {draft.status === "error" ? (
        <p className="sd-error" role="alert">
          {draft.message}
        </p>
      ) : null}
      {draft.status === "ready" ? (
        <ul className="p2-concepts" data-testid="p2-concepts">
          {draft.data.concepts.map((c, i) => (
            <li key={i}>
              <CoverPreview overlay={c.overlay} />
              <span className="sa-hint">
                Phương án {String.fromCharCode(65 + i)}
                {c.rationale ? ` · ${c.rationale}` : ""}
              </span>
              <button aria-pressed={o === c.overlay} className="sa-btn sa-btn--s" onClick={() => set({ overlay: { ...c.overlay } })} type="button">
                Chọn {String.fromCharCode(65 + i)}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {draft.status === "ready" && draft.data.note ? <p className="sa-hint">{draft.data.note}</p> : null}
      {o ? (
        <div className="p2-grid" data-testid="p2-cover-edit">
          <Pills label="Kiểu lớp chữ" onChange={(layout) => edit({ layout })} options={LAYOUTS} value={o.layout as (typeof LAYOUTS)[number][0]} />
          <TextIn label="Nhãn" onChange={(badge_text) => edit({ badge_text })} value={o.badge_text ?? ""} />
          <TextIn label="Dòng giá mỗi đơn vị" onChange={(pack_text) => edit({ pack_text })} value={o.pack_text ?? ""} />
          <TextIn label="Dòng voucher" onChange={(voucher_text) => edit({ voucher_text })} value={o.voucher_text ?? ""} />
          {o.layout === "banner_bottom" ? <TextIn label="Dòng 2" onChange={(hook_text) => edit({ hook_text })} value={o.hook_text ?? ""} /> : null}
        </div>
      ) : null}
      <p className="sa-hint">Juli đề xuất 2–4 lớp chữ từ số của sản phẩm (giá mỗi đơn vị, % giảm, voucher, lợi ích) và công cụ ảnh bìa vẽ chúng lên ảnh thật. Ảnh gốc không bị sửa; chữ lợi ích chỉ dùng điều shop đã nhập. Bạn tự đổi ảnh bìa ở Seller Centre.</p>
    </div>
  );
}

// ── Mô tả ────────────────────────────────────────────────────────────────

export function DescPanel({ form, set, ctx }: P<"description_first_line">) {
  const [draft, run] = useDraft(() => ctx.api.draftDescription({ itemId: ctx.product.item_id, count: 3 }));
  const n = chars(form.text);
  return (
    <div className="p2-panel" data-testid="p2-panel-desc">
      <div className="sd-actions">
        <button className="sa-btn sa-btn--primary" data-testid="p2-desc-draft" disabled={draft.status === "busy"} onClick={run} type="button">
          Viết 3 dòng đầu mô tả
        </button>
      </div>
      {draft.status === "busy" ? (
        <p className="sa-hint" role="status">
          Đang viết…
        </p>
      ) : null}
      {draft.status === "off" ? <LlmOff message={draft.message} /> : null}
      {draft.status === "error" ? (
        <p className="sd-error" role="alert">
          {draft.message}
        </p>
      ) : null}
      {draft.status === "ready" ? (
        <ul className="p2-drafts" data-testid="p2-desc-drafts">
          {draft.data.drafts.map((d, i) => (
            <li key={i}>
              <span>{d.first_line}</span>
              <span className="sa-hint">{d.chars} ký tự</span>
              <button className="sa-btn sa-btn--s" onClick={() => set({ text: d.first_line })} type="button">
                Dùng
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <label className="p2-field p2-field--wide">
        <span className="sd-field__label">Sửa dòng đầu (tối đa {MAX_FIRST_LINE} ký tự)</span>
        <textarea aria-label="Dòng đầu mô tả" className="sv-title__box" onChange={(e) => set({ text: e.target.value.replace(/[\r\n]+/g, " ") })} rows={3} value={form.text} />
      </label>
      <span className={`sa-chip sa-chip--${n > MAX_FIRST_LINE ? "down" : "up"}`} data-testid="p2-desc-count">
        {n}/{MAX_FIRST_LINE}
      </span>
      <p className="sa-hint">Chỉ thay dòng đầu của mô tả; phần còn lại giữ nguyên. Không thêm chứng nhận, độ an toàn hay thành phần shop chưa cung cấp.</p>
    </div>
  );
}

// ── Affiliate / KOL ──────────────────────────────────────────────────────

export function AffiliatePanel({ form, set, ctx }: P<"affiliate">) {
  const sample = ctx.outcome?.cost?.sample ?? null;
  return (
    <div className="p2-panel" data-testid="p2-panel-aff">
      <p className="sa-hint">
        Sản phẩm: <b>{ctx.product.name}</b>
      </p>
      <div className="p2-grid">
        <NumIn label="Hoa hồng mới" onChange={(commission) => set({ commission })} suffix="%" value={form.commission} />
        <TextIn label="Chiến dịch" onChange={(campaign) => set({ campaign })} value={form.campaign} />
        <NumIn label="Số mẫu gửi" onChange={(samples) => set({ samples })} value={form.samples} />
        <NumIn label="Phí ship mỗi mẫu" onChange={(shipFee) => set({ shipFee })} suffix="đ" value={form.shipFee} />
      </div>
      {sample ? (
        <p className="sa-hint" data-testid="p2-aff-sample">
          Mỗi mẫu = giá vốn + đóng gói + ship = {vnd(sample.unit_cost)} · {sample.qty} mẫu = {vnd(sample.total)}
        </p>
      ) : null}
      <p className="sa-hint">Hoa hồng áp cho mọi đơn qua affiliate của sản phẩm; chi phí mẫu tính vào phương án.</p>
    </div>
  );
}

// ── Hiển thị giá + listing ───────────────────────────────────────────────

export function PriceDisplayPanel({ form, set, ctx }: P<"price_display">) {
  const unit = ctx.variations.length === 1 && ctx.variations[0]!.price_per_unit !== null ? ctx.variations[0]!.price_per_unit : null;
  return (
    <div className="p2-panel" data-testid="p2-panel-price">
      <Pills label="Việc cần làm" onChange={(what) => set({ what })} options={[["price_display", "Hiển thị giá mỗi đơn vị"], ["listing_hide", "Ẩn listing"], ["listing_relist", "Đưa lại listing"]]} value={form.what} />
      {form.what === "price_display" ? (
        <>
          <p className="sa-hint">{unit !== null ? `Giá mỗi đơn vị: ${vnd(unit)} trên ảnh bìa và tên phân loại.` : "Giá mỗi đơn vị lấy từ số lượng trong tên phân loại."}</p>
          <TextIn label="Dòng hiển thị (để trống = giá mỗi đơn vị)" onChange={(text) => set({ text })} value={form.text} />
        </>
      ) : null}
      {form.what === "listing_relist" ? <NumIn label="Tồn khi đưa lại" onChange={(stock) => set({ stock })} value={form.stock} /> : null}
      <p className="sa-hint">Đây là thay đổi theo kế hoạch: Juli ghi lại, bạn tự ẩn / đưa lại ở Seller Centre. Chỉ số theo dõi: lượt xem.</p>
    </div>
  );
}
