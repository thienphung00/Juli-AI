"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { BuilderApi, PickerProduct, VariationRow } from "../../../lib/shopee-decisions/builder-api";
import type { BuilderP98Api, ComboBundle, ComboPriceRule, ComboRequest, ComboResponse, ComboRow } from "../../../lib/shopee-decisions/builder-p98-api";
import { errorText } from "../ui";
import { Field, ResultCards, num, pct, vnd } from "../builder-p92/p98-shared";

const PACKS = [3, 5, 10] as const;

type Variations = Readonly<Record<string, readonly VariationRow[]>>;

/** Text a spreadsheet pastes: header row + one line per option, tab separated. */
export function comboTable(rows: readonly ComboRow[]): string {
  const head = ["Tên phân loại", "SKU", "Giá", "Giá/hộp", "Tiết kiệm so với mua lẻ", "Biên ở giá bán", "Biên cuối", "Lợi nhuận/đơn", "Tồn kho gợi ý"];
  const lines = rows.map((r) =>
    [r.option_name, r.sku ?? "", r.price ?? "", r.price_per_box ?? "", r.saving ?? "", r.margin_pct ?? "", r.final_margin_pct ?? "", r.profit_per_order ?? "", r.suggested_stock ?? ""].join("\t"),
  );
  return [head.join("\t"), ...lines].join("\n");
}

export function ComboBuilder({ api, variationsApi, products }: { readonly api: BuilderP98Api; readonly variationsApi: Pick<BuilderApi, "variations">; readonly products: readonly PickerProduct[] }) {
  const [picked, setPicked] = useState<readonly string[]>([]);
  const [vars, setVars] = useState<Variations>({});
  const [ticked, setTicked] = useState<Readonly<Record<string, readonly string[]>>>({});
  const [packs, setPacks] = useState<readonly number[]>([3, 5, 10]);
  const [custom, setCustom] = useState("");
  const [bundles, setBundles] = useState<readonly ComboBundle[]>([]);
  const [bundleQty, setBundleQty] = useState<Readonly<Record<string, string>>>({});
  const [sameVariation, setSameVariation] = useState(true);
  const [soldOnly, setSoldOnly] = useState(true);
  const [maxOptions, setMaxOptions] = useState("60");
  const [kind, setKind] = useState<ComboPriceRule["kind"]>("ladder");
  const [targetMargin, setTargetMargin] = useState("15");
  const [boxPrice, setBoxPrice] = useState("");
  const [overrides, setOverrides] = useState<Readonly<Record<string, number>>>({});
  const [data, setData] = useState<ComboResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [built, setBuilt] = useState(false);
  const [copied, setCopied] = useState(false);
  const seq = useRef(0);

  const toggleProduct = (id: string) => {
    if (picked.includes(id)) {
      setPicked(picked.filter((p) => p !== id));
      return;
    }
    setPicked([...picked, id]);
    if (!vars[id]) {
      variationsApi.variations(id).then(
        (list) => {
          setVars((v) => ({ ...v, [id]: list.variations }));
          setTicked((t) => ({ ...t, [id]: list.variations.map((x) => x.variation_id) }));
        },
        (e: unknown) => setError(errorText(e)),
      );
    }
  };
  const toggleVar = (item: string, id: string) => setTicked((t) => ({ ...t, [item]: (t[item] ?? []).includes(id) ? (t[item] ?? []).filter((x) => x !== id) : [...(t[item] ?? []), id] }));

  const customN = num(custom);
  const sizes = useMemo(() => [...packs, ...(customN && customN >= 2 && !packs.includes(customN) ? [customN] : [])], [packs, customN]);
  const max = num(maxOptions);
  const ready = picked.length > 0 && picked.every((p) => (ticked[p] ?? []).length > 0) && (sizes.length > 0 || bundles.length > 0) && max !== null && max >= 1;

  const request = useMemo<ComboRequest | null>(() => {
    if (!ready) return null;
    const price_rule: ComboPriceRule = kind === "ladder" ? { kind } : kind === "target_margin" ? { kind, target_margin_pct: num(targetMargin) ?? 15 } : { kind, box_price: num(boxPrice) ?? 1 };
    return {
      products: picked.map((id) => ({ item_id: id, variation_ids: ticked[id] ?? [] })),
      pack_sizes: sizes,
      bundles,
      rules: { same_variation: sameVariation, sold_only: soldOnly, max_options: max ?? 60 },
      price_rule,
      overrides,
    };
  }, [ready, picked, ticked, sizes, bundles, sameVariation, soldOnly, max, kind, targetMargin, boxPrice, overrides]);
  const key = JSON.stringify(request);

  useEffect(() => {
    if (!request) {
      setData(null);
      return;
    }
    const n = ++seq.current;
    const timer = window.setTimeout(() => {
      api.combo(request).then(
        (r) => {
          if (n !== seq.current) return;
          setData(r);
          setError(null);
        },
        (e: unknown) => n === seq.current && setError(errorText(e)),
      );
    }, 250);
    return () => window.clearTimeout(timer);
    // `key` says the request changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const setOverride = (rowKey: string, text: string) => {
    const n = num(text);
    setOverrides((o) => {
      const { [rowKey]: _drop, ...rest } = o;
      void _drop;
      return n && n > 0 ? { ...rest, [rowKey]: n } : rest;
    });
  };
  const addBundle = () => {
    const items = picked.map((id) => ({ item_id: id, quantity: num(bundleQty[id] ?? "") ?? 0 })).filter((i) => i.quantity >= 1);
    if (items.length >= 2) setBundles([...bundles, { items }]);
  };
  const copy = () => {
    if (!data) return;
    void navigator.clipboard?.writeText(comboTable(data.rows));
    setCopied(true);
  };
  const nameOf = (id: string) => products.find((p) => p.item_id === id)?.name ?? id;

  return (
    <div className="sa-page" data-testid="combo-builder">
      <h2 className="sa-h1">Tạo combo nhiều SKU</h2>

      <section className="sa-card">
        <h3 className="sa-h2">① Sản phẩm và phân loại</h3>
        <div className="sb-pills">
          {products.slice(0, 40).map((p) => (
            <button aria-pressed={picked.includes(p.item_id)} className={`sb-pill ${picked.includes(p.item_id) ? "sb-pill--on" : ""}`} key={p.item_id} onClick={() => toggleProduct(p.item_id)} type="button">
              {p.name}
            </button>
          ))}
        </div>
        {picked.map((id) => (
          <fieldset key={id} data-testid={`combo-vars-${id}`}>
            <legend>{nameOf(id)}</legend>
            {(vars[id] ?? []).map((v) => (
              <label key={v.variation_id}>
                <input checked={(ticked[id] ?? []).includes(v.variation_id)} onChange={() => toggleVar(id, v.variation_id)} type="checkbox" />
                {v.name}
              </label>
            ))}
          </fieldset>
        ))}
      </section>

      <section className="sa-card">
        <h3 className="sa-h2">② Cỡ gói và gói nhiều sản phẩm</h3>
        <div className="sb-pills">
          {PACKS.map((n) => (
            <button aria-pressed={packs.includes(n)} className={`sb-pill ${packs.includes(n) ? "sb-pill--on" : ""}`} key={n} onClick={() => setPacks(packs.includes(n) ? packs.filter((x) => x !== n) : [...packs, n])} type="button">
              {n} hộp
            </button>
          ))}
          <Field label="Cỡ khác (hộp)">
            <input inputMode="numeric" onChange={(e) => setCustom(e.target.value)} value={custom} />
          </Field>
        </div>
        {picked.length >= 2 ? (
          <div data-testid="combo-bundles">
            <p className="sa-hint">Gói nhiều sản phẩm: nhập số lượng mỗi sản phẩm (để trống = không có trong gói).</p>
            {picked.map((id) => (
              <Field key={id} label={`Số lượng ${nameOf(id)}`}>
                <input inputMode="numeric" onChange={(e) => setBundleQty({ ...bundleQty, [id]: e.target.value })} value={bundleQty[id] ?? ""} />
              </Field>
            ))}
            <button className="sa-btn sa-btn--s" onClick={addBundle} type="button">
              Thêm gói
            </button>
            {bundles.map((b, i) => (
              <span className="sb-pill sb-pill--on" key={i}>
                Gói {i + 1}: {b.items.map((it) => `${it.quantity}× ${nameOf(it.item_id)}`).join(" + ")}{" "}
                <button aria-label={`Bỏ gói ${i + 1}`} onClick={() => setBundles(bundles.filter((_, k) => k !== i))} type="button">
                  ×
                </button>
              </span>
            ))}
          </div>
        ) : null}
      </section>

      <section className="sa-card">
        <h3 className="sa-h2">③ Quy tắc và cách đặt giá</h3>
        <label>
          <input checked={sameVariation} onChange={(e) => setSameVariation(e.target.checked)} type="checkbox" />
          Cùng phân loại trong một gói
        </label>
        <label>
          <input checked={soldOnly} onChange={(e) => setSoldOnly(e.target.checked)} type="checkbox" />
          Chỉ phân loại có bán 30 ngày
        </label>
        <Field label="Tối đa số phương án">
          <input inputMode="numeric" onChange={(e) => setMaxOptions(e.target.value)} value={maxOptions} />
        </Field>
        <Field label="Cách đặt giá">
          <select onChange={(e) => setKind(e.target.value as ComboPriceRule["kind"])} value={kind}>
            <option value="ladder">Giảm giá theo số hộp (mặc định)</option>
            <option value="target_margin">Theo biên cuối mong muốn</option>
            <option value="per_box">Giá cố định mỗi hộp</option>
          </select>
        </Field>
        {kind === "target_margin" ? (
          <Field label="Biên cuối mong muốn (%)">
            <input inputMode="decimal" onChange={(e) => setTargetMargin(e.target.value)} value={targetMargin} />
          </Field>
        ) : null}
        {kind === "per_box" ? (
          <Field label="Giá mỗi hộp (đ)">
            <input inputMode="numeric" onChange={(e) => setBoxPrice(e.target.value)} value={boxPrice} />
          </Field>
        ) : null}
      </section>

      {error ? (
        <p className="sd-error" role="alert">
          {error}
        </p>
      ) : null}

      {data ? (
        <section className="sa-card" data-testid="combo-count">
          <p>
            <b data-testid="combo-count-total">{data.count.total} phương án</b> sẽ được tạo, giữ {data.count.kept}
            {data.count.over_cap > 0 ? `, ${data.count.over_cap} phương án vượt giới hạn ${max}` : ""}.
          </p>
          {data.warnings.map((w) => (
            <p className="sa-hint" key={w} role="status">
              {w}
            </p>
          ))}
          {!built ? (
            <button className="sa-btn sa-btn--primary" data-testid="combo-build" onClick={() => setBuilt(true)} type="button">
              Tạo bảng {data.count.kept} phương án
            </button>
          ) : null}
        </section>
      ) : null}

      {data && built ? (
        <section className="sa-card" data-testid="combo-table-card">
          <div className="sa-card__head">
            <h3 className="sa-h2">Bảng combo</h3>
            <button className="sa-btn sa-btn--s" data-testid="combo-copy" onClick={copy} type="button">
              Sao chép bảng
            </button>
            {copied ? <span className="sa-hint">Đã sao chép</span> : null}
          </div>
          <p className="sa-hint">Sửa giá ở từng dòng để tính lại. Tồn kho gợi ý không tự đồng bộ lên Shopee.</p>
          <div style={{ overflowX: "auto" }}>
            <table className="sa-table" data-testid="combo-table">
              <thead>
                <tr>
                  <th>Tên phân loại</th>
                  <th>SKU</th>
                  <th>Giá</th>
                  <th>Giá/hộp</th>
                  <th>Tiết kiệm so với mua lẻ</th>
                  <th>Biên ở giá bán (chắc chắn)</th>
                  <th>Biên cuối</th>
                  <th>Lợi nhuận/đơn</th>
                  <th>Tồn kho gợi ý</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr data-testid="combo-row" key={r.key}>
                    <td>{r.option_name}</td>
                    <td>{r.sku ?? ""}</td>
                    <td>
                      <input aria-label={`Giá ${r.option_name}`} defaultValue={r.price ?? ""} inputMode="numeric" onBlur={(e) => num(e.target.value) !== r.price && setOverride(r.key, e.target.value)} />
                      {r.overridden ? <span className="sa-hint"> đã sửa</span> : null}
                    </td>
                    <td>{vnd(r.price_per_box)}</td>
                    <td>
                      {vnd(r.saving)} ({pct(r.saving_pct)})
                    </td>
                    <td>{pct(r.margin_pct)}</td>
                    <td>{pct(r.final_margin_pct)}</td>
                    <td>{vnd(r.profit_per_order)}</td>
                    <td>
                      {r.suggested_stock ?? "chưa có"} <span className="sa-hint">không tự đồng bộ</span>
                      {r.below_floor ? (
                        <div className="sd-error" role="alert">
                          Dưới ngưỡng biên tối thiểu
                        </div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ResultCards items={data.rows.map((r) => ({ title: r.option_name, result: r.result }))} />
        </section>
      ) : null}
    </div>
  );
}
