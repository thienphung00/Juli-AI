"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { BuilderApi, BuilderOutcome, PickerResult, PickerProduct } from "../../../lib/shopee-decisions/builder-api";
import { KINDS_92, MAX_VERSIONS, buildVersion, defaultVariationId, initialForms, kindName92, type Forms, type Kind92 } from "../../../lib/shopee-decisions/builder-p92";
import { useReco } from "../../../lib/shopee-decisions/context";
import { SAMPLE_SHOP_BUILDER_KINDS } from "../../../lib/shopee-decisions/sample-scope";
import { useSampleShopReviewer } from "../../../lib/reviewer/mode";
import type { BuilderP98Api } from "../../../lib/shopee-decisions/builder-p98-api";
import { useNarrow } from "../../quyet-dinh/use-narrow";
import { NavLink, errorText } from "../ui";
import type { Entry } from "./compare";
import { ComboPanel, DealSocPanel, DiscountPanel, PriceFlashPanel, SetPanel, VoucherPanel } from "./panels-offers";
import { AdsPanel, AffiliatePanel, CoverPanel, DescPanel, PriceDisplayPanel, TitlePanel } from "./panels-listing";
import { Stepper, VariationChoice } from "./picker";
import { StepChienLuoc } from "./step-chien-luoc";
import { StepPhuongAn } from "./step-phuong-an";
import { StepSoSanh } from "./step-so-sanh";
import { StepSanPham, type ChannelMap } from "./step-san-pham";
import type { ResultState } from "./results";
import { AdsBuilder } from "../ads-builder";
import { ComboBuilder } from "../combo-builder";
import { KolBuilder, type KolCandidate } from "../kol-builder";
import type { PanelCtx } from "./shared";
import { useVariationList } from "./variations";

/**
 * Tự tạo phương án (P100 canvas Flow1..Flow4), four steps: 1 Sản phẩm (cards, the variation choice inline) ·
 * 2 Chiến lược (Ưu đãi / Listing / Truy cập) · 3 Phương án (typed inputs with the live result) · 4 So sánh & lưu
 * (up to 4 versions side by side). `NEXT_PUBLIC_P92_BUILDER=0` brings back the P91 builder (`builder.tsx`).
 */

type Step = "san-pham" | "chien-luoc" | "phuong-an" | "so-sanh";
const STEP_NO: Readonly<Record<Step, 1 | 2 | 3 | 4>> = { "san-pham": 1, "chien-luoc": 2, "phuong-an": 3, "so-sanh": 4 };
const STEP_OF: Readonly<Record<1 | 2 | 3 | 4, Step>> = { 1: "san-pham", 2: "chien-luoc", 3: "phuong-an", 4: "so-sanh" };

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
  { key: "ads", label: "Dịch vụ hiển thị" },
];

/** P98 entry points: three extra builders beside the P92 one (shown only when the P98 client is given). */
function P98Entry({ api, data, from, productId, p98Api, kols }: { readonly api: BuilderApi; readonly data: PickerResult; readonly from: string | null; readonly productId: string | null; readonly p98Api?: BuilderP98Api; readonly kols: readonly KolCandidate[] }) {
  const [mode, setMode] = useState<Mode>("single");
  // P100 S2-C: the sample shop offers only Tiêu đề · Ảnh bìa · Voucher — no P98 builders.
  const sampleShop = useSampleShopReviewer();
  if (sampleShop) return <Builder data={data} from={from} kinds={KINDS_92.filter((k) => SAMPLE_SHOP_BUILDER_KINDS.has(k.key))} productId={productId} />;
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

function Builder({ data, from, productId, kinds = KINDS_92 }: { readonly data: PickerResult; readonly from: string | null; readonly productId: string | null; readonly kinds?: typeof KINDS_92 }) {
  const host = useReco();
  const api = host.builder!;
  const narrow = useNarrow();
  const products = data.products;
  const [product, setProduct] = useState<PickerProduct | null>(() => products.find((p) => p.item_id === productId) ?? null);
  const [step, setStep] = useState<Step>("san-pham");
  const [selIds, setSelIds] = useState<readonly string[] | null>(null);
  const [allVars, setAllVars] = useState(false);
  const [kind, setKind] = useState<Kind92 | null>(null);
  const [forms, setForms] = useState<Forms>(initialForms);
  const [entries, setEntries] = useState<readonly Entry[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const [result, setResult] = useState<{ readonly key: string; readonly state: ResultState } | null>(null);
  const [shopWide, setShopWide] = useState(false);
  const [channel, setChannel] = useState<ChannelMap | null>(null);
  const [aov, setAov] = useState<number | null>(null);
  const nextId = useRef(1);
  const seq = useRef(0);

  // Step ①'s figures; a failure leaves the cards with "—".
  useEffect(() => {
    let live = true;
    const call = api.channelSplitProducts;
    if (!call) return;
    call.call(api, "30d").then(
      (r) => live && setChannel(new Map(r.products.map((p) => [p.product_id, p]))),
      () => live && setChannel(null),
    );
    return () => {
      live = false;
    };
    // The figures are per shop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [host.shopKey]);

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
    if (step !== "phuong-an" || !built.version) return;
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
    setShopWide(false);
  };
  /** "Cả shop": the shop's best seller stands in as the anchor listing; every variation is on. */
  const pickShop = () => {
    const top = products[0];
    if (!top) return;
    pickProduct(top);
    setShopWide(true);
    setAllVars(true);
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
      if (k === "ads" && !f.ads.itemId) next = { ...next, ads: { ...f.ads, itemId: product.item_id } };
      return next;
    });
    setStep("phuong-an");
  };
  const reset = () => {
    if (!kind) return;
    const fresh = initialForms();
    setForms((f) => ({ ...f, [kind]: fresh[kind] }));
    setResult(null);
    if (kind === "combo" && product) setForm("combo", { items: [product.item_id] });
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
    setResult(null);
    setForms((f) => ({ ...f, [kind]: initialForms()[kind] }));
    if (kind === "combo") setForm("combo", { items: [product!.item_id] });
    if (kind === "ads") setForm("ads", { itemId: product!.item_id });
  };
  const editEntry = (i: number) => {
    const e = entries[i];
    if (!e) return;
    setForms(e.forms);
    setKind(e.kind);
    setEditing(i);
    setResult(null);
    setStep("phuong-an");
  };
  const removeEntry = (i: number) => {
    const rest = entries.filter((_, k) => k !== i);
    setEntries(rest);
    if (rest.length === 0 && step === "so-sanh") setStep(product ? "chien-luoc" : "san-pham");
  };

  const back = from === "quyet-dinh" ? { href: host.href({}), label: "Quyết định" } : productId ? { href: host.links.product(productId, { tab: "dx" }), label: "Sản phẩm" } : { href: host.href({}), label: "Quyết định" };
  const planHref = host.plan ? host.href({ plan: true }) : null;
  const stepNo = STEP_NO[step];
  const reachable = [true, !!product, !!product && kind !== null, entries.length > 0];
  const canNext = !!product && (shopWide || chosen.length > 0);
  const kindSet = useMemo(() => new Set<Kind92>(kinds.map((k) => k.key)), [kinds]);

  return (
    <div className="sa-page sb p2" data-testid="p2-page">
      <header className="sa-prodhead">
        <NavLink className="sa-link" href={back.href}>
          ‹ {back.label}
        </NavLink>
        {narrow || !host.shopName ? null : <span className="sa-chip sa-chip--outline sa-row__end">Shopee · {host.shopName}</span>}
      </header>
      <Stepper onGo={(n) => setStep(STEP_OF[n])} reachable={reachable} step={stepNo} />
      {step === "san-pham" || step === "chien-luoc" ? (
        <div>
          <div className="sa-eyebrow" data-testid="p2-eyebrow">
            {step === "san-pham" ? "TỰ TẠO PHƯƠNG ÁN" : shopWide ? "CẢ SHOP" : (product?.name ?? "").toUpperCase()}
          </div>
          <h1 className="sa-h1">{step === "san-pham" ? "Chọn sản phẩm muốn cải thiện" : "Phương án"}</h1>
        </div>
      ) : null}

      {step === "san-pham" ? (
        <StepSanPham
          canNext={canNext}
          channel={channel}
          excludedHidden={data.excluded_hidden}
          exclusionsHref={host.links.exclusions()}
          onNext={() => setStep("chien-luoc")}
          onPick={pickProduct}
          onShop={pickShop}
          products={products}
          selected={product}
          shopWide={shopWide}
        >
          {product && !shopWide ? (
            vars.status === "ready" ? (
              <VariationChoice all={allVars} costLink={costLink} list={vars.data} onAll={() => setAllVars(true)} onToggle={toggleVar} selected={effective} />
            ) : (
              <p className="sa-loading" role="status">
                {vars.status === "error" ? "Chưa tải được phân loại." : "Đang tải phân loại…"}
              </p>
            )
          ) : null}
        </StepSanPham>
      ) : null}

      {product && step === "chien-luoc" ? <StepChienLuoc kinds={kindSet} onBack={() => setStep("san-pham")} onNext={() => kind && pickKind(kind)} onSelect={(k) => setKind(k)} selected={kind} /> : null}

      {product && step === "phuong-an" && kind && ctx ? (
        <StepPhuongAn
          canAdd={!!built.version && (editing !== null || entries.length < MAX_VERSIONS)}
          costLink={costLink}
          ctx={ctx}
          editing={editing}
          entries={entries}
          entriesCount={entries.length}
          forms={forms}
          index={editing !== null ? editing : entries.length}
          kind={kind}
          kindLabel={kindName92(kind)}
          onAdd={addEntry}
          onBack={() => setStep("chien-luoc")}
          onNext={() => setStep("so-sanh")}
          onRemove={removeEntry}
          onReset={reset}
          onSelect={editEntry}
          onUntick={untick}
          productName={shopWide ? "Cả shop" : product.name}
          setForm={setForm}
          state={shown}
        >
          <Panel ctx={ctx} forms={forms} kind={kind} setForm={setForm} />
        </StepPhuongAn>
      ) : null}

      {step === "so-sanh" && entries.length > 0 ? (
        <StepSoSanh
          productName={shopWide ? "Cả shop" : (product?.name ?? "")}
          api={api}
          costLink={costLink}
          entries={entries}
          narrow={narrow}
          onAdd={() => {
            setEditing(null);
            setStep(product ? "chien-luoc" : "san-pham");
          }}
          onBack={() => setStep(product ? "chien-luoc" : "san-pham")}
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
