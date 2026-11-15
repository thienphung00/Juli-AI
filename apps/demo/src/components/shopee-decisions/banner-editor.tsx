"use client";

import { useRef, useState, type ChangeEvent, type CSSProperties } from "react";

import { shopeeImageSrc } from "../../lib/shopee-analytics/image-src";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import {
  applyFix,
  bannerText,
  DAY_MODES,
  DEFAULT_PALETTE,
  drawCover,
  fitToMode,
  KINDS,
  kindOf,
  limitOf,
  newBanner,
  parseValue,
  placeOf,
  SHAPES,
  showValue,
  specOf,
  TEMPLATES,
  templateOf,
  type Banner,
  type BannerSpec,
  type DayMode,
  type TemplateId,
} from "../../lib/shopee-decisions/banner";
import type { BannerContext, BuilderApi } from "../../lib/shopee-decisions/builder-api";

/**
 * Ảnh bìa: the banner editor (P100 S2-E; brief D Flow v4; design
 * https://claude.ai/artifact/4SuySBPc5VbTQFU1SMK1wx). Step by step: 1 Chọn mẫu → 2 Loại ngày →
 * 3 Thêm banner → 4 Kiểm tra → 5 Tải ảnh. The banners sit over the real cover; the PNG
 * (1200 × 1200) is drawn in the browser, nothing is generated. One component for Tự tạo › Ảnh bìa
 * (`onChange` feeds the builder form) and a card (`cardId`: "Lưu banner" stores it on the card).
 */

type Api = Pick<BuilderApi, "banner" | "saveBanner">;

const STEPS = ["Chọn mẫu", "Loại ngày", "Thêm banner", "Kiểm tra", "Tải ảnh"] as const;

export function BannerEditor({
  api,
  itemId,
  cardId = null,
  readOnly = false,
  onChange,
  onSaved,
}: {
  readonly api: Api;
  readonly itemId: string;
  readonly cardId?: string | null;
  readonly readOnly?: boolean;
  /** Tự tạo: the spec as it stands (null while there is no banner yet). */
  readonly onChange?: (spec: BannerSpec | null) => void;
  readonly onSaved?: (spec: BannerSpec) => void;
}) {
  const load = api.banner;
  const res = useResource(() => (load ? load(itemId, cardId) : Promise.reject(new Error("off"))), `banner|${itemId}|${cardId ?? ""}`);
  if (!load) return null;
  if (res.status === "loading") {
    return (
      <p className="sa-hint" role="status">
        Đang mở…
      </p>
    );
  }
  if (res.status !== "ready") {
    return (
      <p className="sd-error" role="alert">
        Chưa mở được trình tạo banner.
      </p>
    );
  }
  return <Editor api={api} cardId={cardId} ctx={res.data} itemId={itemId} key={`${itemId}|${cardId ?? ""}`} onChange={onChange} onSaved={onSaved} readOnly={readOnly} />;
}

function Editor({
  api,
  ctx,
  itemId,
  cardId,
  readOnly,
  onChange,
  onSaved,
}: {
  readonly api: Api;
  readonly ctx: BannerContext;
  readonly itemId: string;
  readonly cardId: string | null;
  readonly readOnly: boolean;
  readonly onChange?: (spec: BannerSpec | null) => void;
  readonly onSaved?: (spec: BannerSpec) => void;
}) {
  const stored = ctx.stored?.spec ?? null;
  const palette = ctx.palette.length ? ctx.palette : DEFAULT_PALETTE;
  const [step, setStep] = useState(stored ? 3 : 1);
  const [template, setTemplate] = useState<TemplateId | null>(stored?.template ?? null);
  const [mode, setMode] = useState<DayMode | null>(stored?.day_mode ?? null);
  const [banners, setBanners] = useState<readonly Banner[]>(stored?.banners ?? []);
  const [upload, setUpload] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState<"idle" | "busy" | "saved" | "error">("idle");
  const fileRef = useRef<HTMLInputElement>(null);

  const cover = upload ?? shopeeImageSrc(ctx.item.cover_url);
  const tpl = templateOf(template);
  const limit = limitOf(mode);
  const spec = specOf(template ?? "toi_gian", mode ?? "ngay_thuong", banners);

  const commit = (next: { template?: TemplateId; mode?: DayMode; banners?: readonly Banner[] }) => {
    const t = next.template ?? template;
    const m = next.mode ?? mode;
    const b = next.banners ?? banners;
    if (next.template) setTemplate(next.template);
    if (next.mode) setMode(next.mode);
    if (next.banners) setBanners(next.banners);
    setSaving("idle");
    onChange?.(t && m && b.length ? specOf(t, m, b) : null);
  };
  const patch = (i: number, p: Partial<Banner>) => commit({ banners: banners.map((b, j) => (j === i ? { ...b, ...p } : b)) });

  const canGo = [true, !!template, !!template && !!mode, banners.length > 0, banners.length > 0];
  const used = new Set(banners.map((b) => b.kind));
  const kinds = KINDS.filter((k) => mode === "mega_sale" || !k.megaOnly);

  const pickImage = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => typeof reader.result === "string" && setUpload(reader.result);
    reader.readAsDataURL(file);
  };

  const download = async () => {
    setNote("");
    const canvas = document.createElement("canvas");
    canvas.width = 1200;
    canvas.height = 1200;
    const g = canvas.getContext("2d");
    if (!g) return;
    let img: HTMLImageElement | null = null;
    if (cover) {
      img = await new Promise<HTMLImageElement | null>((done) => {
        const el = new Image();
        if (!cover.startsWith("data:") && !cover.startsWith("/")) el.crossOrigin = "anonymous";
        el.onload = () => done(el);
        el.onerror = () => done(null);
        el.src = cover;
      });
    }
    drawCover(g, img, spec, palette[0]);
    try {
      const a = document.createElement("a");
      a.href = canvas.toDataURL("image/png");
      a.download = `anh-bia-${itemId}-1200.png`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setNote(`Đã tạo ${a.download}`);
    } catch {
      setNote("Trình duyệt không cho xuất ảnh này. Bấm “Tải ảnh bìa thật” rồi tải lại.");
    }
  };

  const save = async () => {
    if (!api.saveBanner) return;
    setSaving("busy");
    try {
      const out = await api.saveBanner({ itemId, cardId, spec });
      setSaving("saved");
      onSaved?.(out.spec);
    } catch {
      setSaving("error");
    }
  };

  const checks = spec.checks;
  const placeStyle = (b: Banner): CSSProperties => {
    const p = placeOf(b.position, tpl.frame);
    const strip = b.shape === "ngang";
    const fill = tpl.fill || strip;
    return {
      ...(p.top !== undefined ? { top: `${p.top}%` } : { bottom: `${p.bottom}%` }),
      ...(p.left !== undefined ? { left: `${p.left}%` } : { right: `${p.right}%` }),
      ...(strip ? { width: "100%", borderRadius: 0 } : { maxWidth: `${p.w}%`, borderRadius: `${tpl.radius}px` }),
      textAlign: p.align,
      background: fill ? b.colour : "#ffffff",
      color: fill ? "#ffffff" : b.colour,
      borderColor: b.colour,
    };
  };

  return (
    <section aria-label="Tạo banner ảnh bìa" className="bn" data-testid="bn-editor">
      <ol className="bn-steps">
        {STEPS.map((label, i) => {
          const n = i + 1;
          return (
            <li key={label}>
              <button aria-current={step === n ? "step" : undefined} className={`bn-step${step === n ? " bn-step--on" : ""}${step > n ? " bn-step--done" : ""}`} disabled={!canGo[i]} onClick={() => setStep(n)} type="button">
                <span className="bn-step__n">{n}</span>
                {label}
              </button>
            </li>
          );
        })}
      </ol>

      <div className="bn-body">
        <div className="bn-preview">
          <div className={`bn-cover${tpl.frame && template ? " bn-cover--frame" : ""}`} data-testid="bn-cover" style={tpl.frame && template ? { borderColor: palette[0] } : undefined}>
            {/* eslint-disable-next-line @next/next/no-img-element -- a seller's own cover or upload, drawn as is */}
            {cover ? <img alt={`Ảnh bìa ${ctx.item.name}`} className="bn-cover__img" src={cover} /> : null}
            <span aria-hidden="true" className="bn-cover__voucher">
              Shopee đặt voucher ở đây
            </span>
            {banners.map((b, i) => {
              const t = bannerText(b.kind, b.values);
              return (
                <span className={`bn-box${b.shape === "ngang" ? " bn-box--strip" : ""}`} data-testid={`bn-box-${b.kind}`} key={`${b.kind}-${i}`} style={placeStyle(b)}>
                  <b>{t.head}</b>
                  {t.sub ? <small>{t.sub}</small> : null}
                </span>
              );
            })}
          </div>
          <p className="bn-summary" data-testid="bn-summary">
            {template ? `Mẫu ${tpl.name}` : "Chưa chọn mẫu"} · {mode ? DAY_MODES.find((m) => m.id === mode)?.name : "chưa chọn loại ngày"} · {banners.length}/{limit} banner
          </p>
          <button className="sa-btn sa-btn--s" onClick={() => fileRef.current?.click()} type="button">
            Tải ảnh bìa thật
          </button>
          <input accept="image/png,image/jpeg,image/webp" aria-label="Tải ảnh bìa thật" className="bn-file" onChange={pickImage} ref={fileRef} type="file" />
        </div>

        <div className="bn-panel">
          <p className="bn-product">
            <b>{ctx.item.name}</b> · {ctx.item.item_id}
          </p>

          {step === 1 ? (
            <div className="bn-choices" data-testid="bn-step-1">
              <h3>1 · Chọn mẫu</h3>
              {TEMPLATES.map((t) => (
                <button aria-pressed={template === t.id} className="bn-choice" key={t.id} onClick={() => commit({ template: t.id })} type="button">
                  <span aria-hidden="true" className={`bn-thumb${t.frame ? " bn-thumb--frame" : ""}`} style={t.frame ? { borderColor: palette[0] } : undefined}>
                    <span className="bn-thumb__box" style={t.fill ? { background: palette[0], borderRadius: t.radius / 2 } : { borderColor: palette[0], borderRadius: t.radius / 2 }} />
                  </span>
                  <b>{t.name}</b>
                  <span>{t.note}</span>
                </button>
              ))}
            </div>
          ) : null}

          {step === 2 ? (
            <div className="bn-choices bn-choices--two" data-testid="bn-step-2">
              <h3>2 · Ngày thường hay Mega Sale</h3>
              {DAY_MODES.map((m) => (
                <button aria-pressed={mode === m.id} className="bn-choice" key={m.id} onClick={() => commit({ mode: m.id, banners: fitToMode(banners, m.id) })} type="button">
                  <b>{m.name}</b>
                  <span>{m.note}</span>
                  <span className="bn-limit">Tối đa {m.limit} banner</span>
                </button>
              ))}
            </div>
          ) : null}

          {step === 3 ? (
            <div data-testid="bn-step-3">
              <h3>
                3 · Thêm banner <span className="bn-count">{banners.length} / {limit} banner</span>
              </h3>
              <div className="bn-add">
                {kinds.map((k) => (
                  <button className="bn-pill" data-testid={`bn-add-${k.id}`} disabled={readOnly || banners.length >= limit || used.has(k.id)} key={k.id} onClick={() => commit({ banners: [...banners, newBanner(k, banners, palette, ctx.prefill[k.id])] })} type="button">
                    + {k.title} ({SHAPES[k.shape].name})
                  </button>
                ))}
              </div>
              {banners.length === 0 ? <p className="sa-hint">Chưa có banner. Chọn một loại ở trên.</p> : null}
              {banners.map((b, i) => {
                const k = kindOf(b.kind);
                if (!k) return null;
                return (
                  <fieldset className="bn-item" data-testid={`bn-item-${b.kind}`} disabled={readOnly} key={`${b.kind}-${i}`}>
                    <legend>
                      {k.title} · {SHAPES[k.shape].name}
                    </legend>
                    <p className="bn-source">{k.source}</p>
                    <button className="sa-btn sa-btn--s bn-remove" onClick={() => commit({ banners: banners.filter((_, j) => j !== i) })} type="button">
                      Bỏ
                    </button>
                    <div className="bn-fields">
                      {k.fields.map((fd) => (
                        <label className="bn-field" key={fd.key}>
                          <span>{fd.label}</span>
                          <input
                            inputMode={fd.type === "text" ? undefined : "decimal"}
                            onChange={(e) => {
                              const v = parseValue(fd.type, e.target.value);
                              const sources = { ...b.sources };
                              delete sources[fd.key];
                              patch(i, { values: { ...b.values, [fd.key]: fd.type === "text" ? e.target.value.slice(0, 60) : v }, sources });
                            }}
                            placeholder={fd.hint}
                            value={showValue(fd.type, b.values[fd.key])}
                          />
                        </label>
                      ))}
                    </div>
                    <div className="bn-row" role="group" aria-label="Vị trí">
                      <span>Vị trí</span>
                      {SHAPES[k.shape].positions.map(([pos, label]) => (
                        <button aria-pressed={b.position === pos} className="bn-pill" key={pos} onClick={() => patch(i, { position: pos })} type="button">
                          {label}
                        </button>
                      ))}
                    </div>
                    <div className="bn-row" role="group" aria-label="Màu">
                      <span>Màu</span>
                      {palette.map((c) => (
                        <button aria-label={`Màu ${c}`} aria-pressed={b.colour.toUpperCase() === c.toUpperCase()} className="bn-swatch" key={c} onClick={() => patch(i, { colour: c })} style={{ background: c }} type="button" />
                      ))}
                    </div>
                  </fieldset>
                );
              })}
            </div>
          ) : null}

          {step === 4 ? (
            <div data-testid="bn-step-4">
              <h3>4 · Kiểm tra và tối ưu</h3>
              {checks.length === 0 ? (
                <p className="bn-ok" role="status">
                  Không thấy vấn đề. Có thể tải ảnh.
                </p>
              ) : (
                <ul className="bn-issues">
                  {checks.map((c, i) => {
                    const fixed = applyFix(spec, c);
                    return (
                      <li data-testid={`bn-check-${c.code}`} key={`${c.code}-${i}`}>
                        <b>{c.title}</b>
                        <span>{c.fix}</span>
                        {fixed && !readOnly ? (
                          <button className="sa-btn sa-btn--s" onClick={() => commit({ banners: fixed })} type="button">
                            Áp dụng
                          </button>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          ) : null}

          {step === 5 ? (
            <div data-testid="bn-step-5">
              <h3>5 · Tải ảnh</h3>
              <p className="sa-hint">PNG 1200 × 1200</p>
              <div className="sd-actions">
                <button className="sa-btn sa-btn--primary" data-testid="bn-download" onClick={() => void download()} type="button">
                  Tải ảnh PNG
                </button>
                {cardId && api.saveBanner && !readOnly ? (
                  <button className="sa-btn" data-testid="bn-save" disabled={saving === "busy"} onClick={() => void save()} type="button">
                    {saving === "saved" ? "Đã lưu vào thẻ" : "Lưu banner vào thẻ"}
                  </button>
                ) : null}
              </div>
              {note ? (
                <p className="sa-hint" role="status">
                  {note}
                </p>
              ) : null}
              {saving === "error" ? (
                <p className="sd-error" role="alert">
                  Chưa lưu được banner.
                </p>
              ) : null}
            </div>
          ) : null}

          <div className="bn-nav">
            {step > 1 ? (
              <button className="sa-btn" onClick={() => setStep(step - 1)} type="button">
                Quay lại
              </button>
            ) : null}
            {step < 5 ? (
              <button className="sa-btn sa-btn--primary" data-testid="bn-next" disabled={!canGo[step]} onClick={() => setStep(step + 1)} type="button">
                {step === 3 ? "Kiểm tra" : step === 4 ? "Đến bước tải ảnh" : "Tiếp tục"}
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}

/** The card's banner (cover and voucher cards): open the editor on this card. */
export function CardBanner({ api, cardId, itemId, readOnly }: { readonly api: Api; readonly cardId: string; readonly itemId: string; readonly readOnly: boolean }) {
  const [open, setOpen] = useState(false);
  if (!api.banner) return null;
  return (
    <section aria-label="Banner ảnh bìa" className="sd-panel bn-card" data-testid="bn-card">
      <div className="bn-card__head">
        <h2>Banner ảnh bìa</h2>
        <button aria-expanded={open} className="sa-btn sa-btn--s" data-testid="bn-card-open" onClick={() => setOpen(!open)} type="button">
          {open ? "Đóng" : readOnly ? "Xem banner" : "Tạo / sửa banner"}
        </button>
      </div>
      {open ? <BannerEditor api={api} cardId={cardId} itemId={itemId} readOnly={readOnly} /> : null}
    </section>
  );
}
