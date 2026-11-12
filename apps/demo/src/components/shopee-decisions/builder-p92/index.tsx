"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { BuilderApi, BuilderOutcome, PickerResult, PickerProduct } from "../../../lib/shopee-decisions/builder-api";
import { KINDS_92, MAX_VERSIONS, buildVersion, defaultVariationId, initialForms, kindName92, type Forms, type Kind92 } from "../../../lib/shopee-decisions/builder-p92";
import { useReco } from "../../../lib/shopee-decisions/context";
import type { BuilderP98Api } from "../../../lib/shopee-decisions/builder-p98-api";
import { useNarrow } from "../../quyet-dinh/use-narrow";
import { NavLink, errorText } from "../ui";
import { CompareView, type Entry } from "./compare";
import { ComboPanel, DealSocPanel, DiscountPanel, ListingComboPanel, PriceFlashPanel, SetPanel, VoucherPanel } from "./panels-offers";
import { AdsPanel, AffiliatePanel, CoverPanel, DescPanel, PriceDisplayPanel, TitlePanel } from "./panels-listing";
import { ProductPicker, ProductStrip, Steps, VariationStep, VariationStrip } from "./picker";
import { ResultBlock, type ResultState } from "./results";
import { AdsBuilder } from "../ads-builder";
import { ComboBuilder } from "../combo-builder";
import { KolBuilder, type KolCandidate } from "../kol-builder";
import type { PanelCtx } from "./shared";
import { useVariationList } from "./variations";

/**
 * Tự tạo phương án · So sánh phương án, P92 (artboards `TuTaoPhuongAnP92`, `…Kinds`, `SoSanhPhuongAn` and their
 * mobile versions). Steps: ① product (all active listings) · ② variation · ③ strategy kind · ④ typed inputs with the
 * live result · then up to 4 versions of any kinds side by side. `NEXT_PUBLIC_P92_BUILDER=0` brings back the P91
 * builder (`builder.tsx`).
 */

type Step = "pick" | "variation" | "kinds" | "panel" | "compare";

type PickerState = { readonly status: "loading" } | { readonly status: "error"; readonly message: string } | { readonly status: "ready"; readonly data: PickerResult };

export function BuilderP92View({ from, productId, p98Api, kols = [] }: { readonly from: string | null; readonly productId: string | null; readonly p98Api?: BuilderP98Api; readonly kols?: readonly KolCandidate[] }) {
  const host = useReco();
  const api = host.builder!;
  const [state, setState] = useState<PickerState>({ status: "loading" });
  useEffect(() => {
    let live = true;
    api.products({ sort: "gmv_90d", limit: 1000 }).then(
      (data) => live && setState({ status: "ready", data }),
      (e: unknown) => live && setState({ status: "error", message: errorText(e) }),
    );
    return () => {
      live = false;
    };
    // The list is per shop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [host.shopKey]);
  if (state.status === "loading") {
    return (
      <p className="sa-loading" role="status">
        Đang tải sản phẩm…
      </p>
    );
  }
  if (state.status === "error") {
    return (
      <div className="sa-page">
        <p className="sd-error" role="alert">
          {state.message}
        </p>
      </div>
    );
  }
  return <P98Entry api={api} data={state.data} from={from} kols={kols} p98Api={p98Api} productId={productId} />;
}

type Mode = "single" | "combo" | "kol" | "ads";
const MODES: readonly { readonly key: Mode; readonly label: string }[] = [
  { key: "single", label: "Từng phương án" },
  { key: "combo", label: "Combo nhiều SKU" },
  { key: "kol", label: "KOL" },
  { key: "ads", label: "Quảng cáo" },
];

/** P98 entry points: three extra builders beside the P92 one (shown only when the P98 client is given). */
function P98Entry({ api, data, from, productId, p98Api, kols }: { readonly api: BuilderApi; readonly data: PickerResult; readonly from: string | null; readonly productId: string | null; readonly p98Api?: BuilderP98Api; readonly kols: readonly KolCandidate[] }) {
  const [mode, setMode] = useState<Mode>("single");
  if (!p98Api) return <Builder data={data} from={from} productId={productId} />;
  return (
    <>
      <nav aria-label="Loại công cụ" className="sb-pills p98-modes" data-testid="p98-modes">
        {MODES.map((m) => (
          <button aria-pressed={mode === m.key} className={`sb-pill ${mode === m.key ? "sb-pill--on" : ""}`} data-testid={`p98-mode-${m.key}`} key={m.key} onClick={() => setMode(m.key)} type="button">
            {m.label}
          </button>
        ))}
      </nav>
      {mode === "single" ? <Builder data={data} from={from} productId={productId} /> : null}
      {mode === "combo" ? <ComboBuilder api={p98Api} products={data.products} variationsApi={api} /> : null}
      {mode === "kol" ? <KolBuilder api={p98Api} kols={kols} products={data.products} /> : null}
      {mode === "ads" ? <AdsBuilder api={p98Api} products={data.products} /> : null}
    </>
  );
}

function Builder({ data, from, productId }: { readonly data: PickerResult; readonly from: string | null; readonly productId: string | null }) {
  const host = useReco();
  const api = host.builder!;
  const narrow = useNarrow();
  const products = data.products;
  const [product, setProduct] = useState<PickerProduct | null>(() => products.find((p) => p.item_id === productId) ?? null);
  const [step, setStep] = useState<Step>(product ? "variation" : "pick");
  const [selIds, setSelIds] = useState<readonly string[] | null>(null);
  const [allVars, setAllVars] = useState(false);
  const [kind, setKind] = useState<Kind92 | null>(null);
  const [forms, setForms] = useState<Forms>(initialForms);
  const [entries, setEntries] = useState<readonly Entry[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const [result, setResult] = useState<{ readonly key: string; readonly state: ResultState } | null>(null);
  const [aov, setAov] = useState<number | null>(null);
  const nextId = useRef(1);
  const seq = useRef(0);

  const costLink = host.links.costImport(null, "tu-tao");
  const vars = useVariationList(api, product?.item_id ?? null);
  const list = vars.status === "ready" ? vars.data : null;
  const first = list ? defaultVariationId(list.variations) : undefined;
  const effective = useMemo<readonly string[]>(() => selIds ?? (first !== undefined ? [first] : []), [selIds, first]);
  const chosen = useMemo(() => (list ? list.variations.filter((v) => allVars || effective.includes(v.variation_id)) : []), [list, allVars, effective]);

  const built = useMemo(() => (kind && product ? buildVersion(kind, forms, { product, variations: chosen }) : { version: null, problem: null }), [kind, forms, product, chosen]);
  const key = built.version ? JSON.stringify(built.version) : "";
  const ctx: PanelCtx | null = product ? { api, product, variations: chosen, products, aov, outcome: result?.state.status === "ready" && result.key === key ? result.state.outcome : null, narrow, costLink, market: host.market ?? null } : null;

  useEffect(() => {
    if (step !== "panel" || !built.version) return;
    const n = ++seq.current;
    const version = built.version;
    const timer = window.setTimeout(() => {
      api.evaluate([version]).then(
        (r) => {
          if (n !== seq.current) return;
          const o: BuilderOutcome | undefined = r.versions[0];
          if (r.today.aov !== null) setAov(r.today.aov);
          setResult({ key, state: o ? { status: "ready", outcome: o } : { status: "error", message: "Chưa tính được." } });
        },
        (e: unknown) => n === seq.current && setResult({ key, state: { status: "error", message: errorText(e) } }),
      );
    }, 350);
    return () => window.clearTimeout(timer);
    // `key` says the version changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, step]);

  const shown: ResultState = !built.version ? { status: "idle", problem: built.problem } : result?.key === key ? result.state : { status: "busy" };
  const setForm = <K extends Kind92>(k: K, patch: Partial<Forms[K]>) => setForms((f) => ({ ...f, [k]: { ...f[k], ...patch } }));

  const pickProduct = (p: PickerProduct) => {
    setProduct(p);
    setSelIds(null);
    setAllVars(false);
    setForms(initialForms());
    setKind(null);
    setResult(null);
    setStep("variation");
  };
  const toggleVar = (id: string) => {
    setAllVars(false);
    const cur = effective;
    setSelIds(cur.includes(id) ? (cur.length > 1 ? cur.filter((x) => x !== id) : cur) : [...cur, id]);
  };
  const pickKind = (k: Kind92) => {
    if (!product) return;
    setKind(k);
    setResult(null);
    setForms((f) => {
      let next = f;
      if (k === "combo" && f.combo.items.length === 0) next = { ...next, combo: { ...f.combo, items: [product.item_id] } };
      if (k === "listing_combo" && f.listing_combo.members.length === 0) next = { ...next, listing_combo: { ...f.listing_combo, members: [product.item_id] } };
      if (k === "ads" && !f.ads.itemId) next = { ...next, ads: { ...f.ads, itemId: product.item_id } };
      return next;
    });
    setStep("panel");
  };
  const reset = () => {
    if (!kind) return;
    const fresh = initialForms();
    setForms((f) => ({ ...f, [kind]: fresh[kind] }));
    setResult(null);
    if (kind === "combo" && product) setForm("combo", { items: [product.item_id] });
    if (kind === "listing_combo" && product) setForm("listing_combo", { members: [product.item_id] });
  };
  /** P97 D85.13: unticking a target in the result takes it out of the form; the version is then evaluated again. */
  const untick = (id: string) => {
    if (!kind) return;
    if (kind === "product_discount") setForm("product_discount", { targets: forms.product_discount.targets.filter((t) => t !== id) });
    else if (kind === "affiliate") setForm("affiliate", { targets: forms.affiliate.targets.filter((t) => t !== id) });
    else if (kind === "voucher") setForm("voucher", { items: forms.voucher.items.filter((t) => t !== id) });
    else if (kind === "combo") setForm("combo", { items: forms.combo.items.filter((t) => t !== id) });
    else if (kind === "ads") {
      const next = forms.ads.campaignKeys.filter((t) => t !== id);
      setForm("ads", { campaignKeys: next, campaignKey: next[0] ?? "" });
    }
  };
  const addEntry = () => {
    if (!built.version || !kind) return;
    // P96d: the names the compare table shows for this version's ids, as they are now
    const names = {
      products: Object.fromEntries(products.map((p) => [p.item_id, p.name])),
      variations: Object.fromEntries((list?.variations ?? []).map((v) => [v.variation_id, v.name])),
    };
    if (editing !== null) setEntries((all) => all.map((e, i) => (i === editing ? { ...e, kind, forms, version: built.version!, names } : e)));
    else setEntries((all) => [...all, { id: nextId.current++, kind, forms, version: built.version!, names }]);
    setEditing(null);
    setStep("kinds");
  };
  const editEntry = (i: number) => {
    const e = entries[i];
    if (!e) return;
    setForms(e.forms);
    setKind(e.kind);
    setEditing(i);
    setResult(null);
    setStep("panel");
  };
  const removeEntry = (i: number) => {
    const rest = entries.filter((_, k) => k !== i);
    setEntries(rest);
    if (rest.length === 0 && step === "compare") setStep(product ? "kinds" : "pick");
  };

  const back = from === "quyet-dinh" ? { href: host.href({}), label: "Quyết định" } : productId ? { href: host.links.product(productId, { tab: "dx" }), label: "Sản phẩm" } : { href: host.href({}), label: "Quyết định" };
  const planHref = host.plan ? host.href({ plan: true }) : null;
  const stepNo = step === "pick" ? 1 : step === "variation" ? 2 : step === "kinds" ? 3 : 4;

  return (
    <div className="sa-page sb p2" data-testid="p2-page">
      <header className="sa-prodhead">
        <NavLink className="sa-link" href={back.href}>
          ‹ {back.label}
        </NavLink>
        {narrow ? null : <div className="sa-eyebrow">TỰ TẠO PHƯƠNG ÁN · SO SÁNH PHƯƠNG ÁN</div>}
        {narrow || !host.shopName ? null : <span className="sa-chip sa-chip--outline sa-row__end">Shopee · {host.shopName}</span>}
      </header>
      <div>
        {narrow ? <div className="sa-eyebrow">TỰ TẠO PHƯƠNG ÁN</div> : null}
        <h1 className="sa-h1">{narrow ? "Chọn sản phẩm, phân loại và loại chiến lược" : "Tự đặt ưu đãi, xem số trước khi quyết định"}</h1>
        <p className="sa-hint">
          {narrow
            ? "Mọi sản phẩm đang bán đều chọn được, không chỉ sản phẩm có đơn 30 ngày qua."
            : "Chọn sản phẩm (mọi sản phẩm đang bán, không chỉ sản phẩm có đơn 30 ngày qua), chọn phân loại, rồi chọn loại chiến lược. Chưa lưu gì cho đến khi bạn chọn một phương án."}
        </p>
      </div>
      {step !== "compare" ? <Steps step={stepNo as 1 | 2 | 3 | 4} /> : null}

      {entries.length > 0 ? (
        <div className="p2-tray" data-testid="p2-tray">
          <span className="sa-hint">Đã thêm:</span>
          {entries.map((e, i) => (
            <span className="sb-pill sb-pill--on" key={e.id}>
              P{i + 1} · {String(e.version.label ?? kindName92(e.kind))}
            </span>
          ))}
          <button className="sa-btn sa-btn--primary sa-btn--s" data-testid="p2-open-compare" disabled={step === "compare"} onClick={() => setStep("compare")} type="button">
            So sánh phương án ({entries.length}/{MAX_VERSIONS}) ›
          </button>
        </div>
      ) : null}

      {step === "pick" ? <ProductPicker excludedHidden={data.excluded_hidden} exclusionsHref={host.links.exclusions()} onPick={pickProduct} products={products} /> : null}

      {product && step !== "pick" && step !== "compare" ? <ProductStrip onChange={() => setStep("pick")} product={product} /> : null}

      {product && (step === "kinds" || step === "panel") && chosen.length > 0 ? <VariationStrip all={allVars} onChange={() => setStep("variation")} variations={chosen} /> : null}

      {product && step === "variation" ? (
        vars.status === "ready" ? (
          <VariationStep
            all={allVars}
            costLink={costLink}
            list={vars.data}
            onAll={() => setAllVars(true)}
            onNext={() => setStep("kinds")}
            onToggle={toggleVar}
            selected={effective}
          />
        ) : (
          <p className="sa-loading" role="status">
            {vars.status === "error" ? "Chưa tải được phân loại." : "Đang tải phân loại…"}
          </p>
        )
      ) : null}

      {product && step === "kinds" ? (
        <section className="sa-card" data-testid="p2-kinds">
          <div className="sa-card__head">
            <h2 className="sa-h2">③ Loại chiến lược</h2>
            <span className="sa-hint">Mỗi loại ghi sẵn chỉ số chính mà phương án sẽ được đo</span>
          </div>
          <div className="p2-kinds">
            {KINDS_92.map((k) => (
              <button className="p2-kind" data-testid={`p2-kind-${k.key}`} key={k.key} onClick={() => pickKind(k.key)} type="button">
                <b>{k.name}</b>
                <span>Chỉ số chính: {k.drivers}</span>
              </button>
            ))}
          </div>
          <p className="sa-hint">So sánh tối đa 4 phương án khác loại ở So sánh phương án.</p>
        </section>
      ) : null}

      {product && step === "panel" && kind && ctx ? (
        <>
          <div className="p2-panelhead">
            <button className="sa-link p2-linkbtn" onClick={() => setStep("kinds")} type="button">
              ‹ Chọn loại chiến lược
            </button>
            <h2 className="sa-h2">{kindName92(kind)}</h2>
            <span className="sa-hint">Nhập số, không có thanh trượt · P{editing !== null ? editing + 1 : entries.length + 1}</span>
          </div>
          <div className="p2-split">
            <section className="sa-card p2-inputs" data-testid="p2-inputs">
              <Panel ctx={ctx} forms={forms} kind={kind} setForm={setForm} />
            </section>
            <div className="p2-side">
              <ResultBlock costLink={costLink} index={editing !== null ? editing : entries.length} onUntick={untick} state={shown} title={kindName92(kind)} />
              <div className="sd-actions">
                <button className="sa-btn sa-btn--primary" data-testid="p2-add" disabled={!built.version || (editing === null && entries.length >= MAX_VERSIONS) || shown.status !== "ready" || !shown.outcome.ok} onClick={addEntry} type="button">
                  {editing !== null ? `Cập nhật P${editing + 1}` : "+ Thêm vào So sánh phương án"}
                </button>
                <button className="sa-btn" onClick={reset} type="button">
                  Đặt lại
                </button>
              </div>
              {editing === null && entries.length >= MAX_VERSIONS ? <p className="sa-hint">Đã đủ 4 phương án: sửa hoặc xoá một phương án để thêm.</p> : null}
            </div>
          </div>
        </>
      ) : null}

      {step === "compare" && entries.length > 0 ? (
        <CompareView
          api={api}
          costLink={costLink}
          entries={entries}
          narrow={narrow}
          onAdd={() => {
            setEditing(null);
            setStep(product ? "kinds" : "pick");
          }}
          onBack={() => setStep(product ? "kinds" : "pick")}
          onEdit={editEntry}
          onRemove={removeEntry}
          planHref={planHref}
          readOnly={!!host.readOnly}
          staffDraft={!!host.staff}
        />
      ) : null}
    </div>
  );
}

function Panel({ kind, forms, setForm, ctx }: { readonly kind: Kind92; readonly forms: Forms; readonly setForm: <K extends Kind92>(k: K, patch: Partial<Forms[K]>) => void; readonly ctx: PanelCtx }) {
  switch (kind) {
    case "voucher":
      return <VoucherPanel ctx={ctx} form={forms.voucher} set={(p) => setForm("voucher", p)} />;
    case "combo":
      return <ComboPanel ctx={ctx} form={forms.combo} set={(p) => setForm("combo", p)} />;
    case "listing_combo":
      return <ListingComboPanel ctx={ctx} form={forms.listing_combo} set={(p) => setForm("listing_combo", p)} />;
    case "deal_soc":
      return <DealSocPanel ctx={ctx} form={forms.deal_soc} set={(p) => setForm("deal_soc", p)} />;
    case "product_discount":
      return <DiscountPanel ctx={ctx} form={forms.product_discount} set={(p) => setForm("product_discount", p)} />;
    case "price_flash":
      return <PriceFlashPanel ctx={ctx} form={forms.price_flash} set={(p) => setForm("price_flash", p)} />;
    case "variation_set":
      return <SetPanel ctx={ctx} form={forms.variation_set} set={(p) => setForm("variation_set", p)} />;
    case "ads":
      return <AdsPanel ctx={ctx} form={forms.ads} set={(p) => setForm("ads", p)} />;
    case "title":
      return <TitlePanel ctx={ctx} form={forms.title} set={(p) => setForm("title", p)} />;
    case "cover_image":
      return <CoverPanel ctx={ctx} form={forms.cover_image} set={(p) => setForm("cover_image", p)} />;
    case "description_first_line":
      return <DescPanel ctx={ctx} form={forms.description_first_line} set={(p) => setForm("description_first_line", p)} />;
    case "affiliate":
      return <AffiliatePanel ctx={ctx} form={forms.affiliate} set={(p) => setForm("affiliate", p)} />;
    case "price_display":
      return <PriceDisplayPanel ctx={ctx} form={forms.price_display} set={(p) => setForm("price_display", p)} />;
  }
}
