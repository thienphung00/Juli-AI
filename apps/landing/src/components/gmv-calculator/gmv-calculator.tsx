"use client";

import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";

import { Button } from "../ui/button";
import {
  calculateFromCounts,
  calculateFromRates,
  equalUplifts,
  FACTOR_LABELS,
  FACTOR_ORDER,
  factorValue,
  formatCount,
  formatPercent,
  formatVietnameseNumber,
  formatVnd,
  gmvWithFactor,
  parseVietnameseNumber,
  relativeChange,
  type CountInputs,
  type FactorKey,
  type Funnel,
  type RateInputs,
} from "./calc";
import { EXAMPLE_NOTE, GMV_POST_ANCHORS, STEP_GUIDES, type GmvPostAnchor } from "./content";
import styles from "./gmv-calculator.module.css";

/**
 * The free GMV calculator (D49.1, P43). Everything runs here, in the browser:
 * no fetch, no storage, no analytics event. The only links out are the
 * "GMV là gì" post (passed in as `postHref` only once it is published, since an
 * indexable page never links a noindex draft) and the product page.
 */

type Mode = "rates" | "counts";
type RateKey = keyof RateInputs;
type CountKey = "impressions" | "clicks" | "orders" | "gmv" | "aov";

const EMPTY_RATES: RateInputs = { impressions: "", ctrPercent: "", ctorPercent: "", aov: "" };
const EMPTY_COUNTS: CountInputs = { impressions: "", clicks: "", orders: "", money: "gmv", gmv: "", aov: "" };

/** The hypothetical example of the "GMV là gì" post: 50.000 × 3 % × 4 % × 180.000 ₫ = 10.800.000 ₫. */
export const EXAMPLE_RATES: RateInputs = { impressions: "50.000", ctrPercent: "3", ctorPercent: "4", aov: "180.000" };
export const EXAMPLE_COUNTS: CountInputs = {
  impressions: "50.000",
  clicks: "1.500",
  orders: "60",
  money: "gmv",
  gmv: "10.800.000",
  aov: "",
};

interface FieldSpec<K extends string> {
  key: K;
  label: string;
  hint: string;
  suffix?: string;
}

const RATE_FIELDS: readonly FieldSpec<RateKey>[] = [
  { key: "impressions", label: "Lượt hiển thị sản phẩm", hint: "Số lần sản phẩm xuất hiện trước người xem. Ví dụ: 50.000" },
  { key: "ctrPercent", label: "CTR (tỷ lệ nhấp)", hint: "Lượt nhấp ÷ Lượt hiển thị. Ví dụ: 3 hoặc 3,5", suffix: "%" },
  { key: "ctorPercent", label: "CTOR (tỷ lệ từ nhấp đến đặt hàng)", hint: "Đơn hàng SKU ÷ Lượt nhấp. Ví dụ: 4", suffix: "%" },
  { key: "aov", label: "AOV (SKU)", hint: "GMV ÷ Đơn hàng SKU, tính bằng đồng. Ví dụ: 180.000", suffix: "₫" },
];

const COUNT_FIELDS: readonly FieldSpec<Exclude<CountKey, "gmv" | "aov">>[] = [
  { key: "impressions", label: "Lượt hiển thị sản phẩm", hint: "Ví dụ: 50.000" },
  { key: "clicks", label: "Lượt nhấp vào sản phẩm", hint: "Ví dụ: 1.500" },
  { key: "orders", label: "Đơn hàng SKU", hint: "Ví dụ: 60" },
];

const MONEY_FIELDS: Record<"gmv" | "aov", FieldSpec<"gmv" | "aov">> = {
  gmv: { key: "gmv", label: "GMV", hint: "Tổng GMV của cùng kỳ, tính bằng đồng. Ví dụ: 10.800.000", suffix: "₫" },
  aov: { key: "aov", label: "AOV (SKU)", hint: "Tính bằng đồng. Ví dụ: 180.000", suffix: "₫" },
};

export function formatFactor(factor: FactorKey, value: number): string {
  if (factor === "impressions") return formatCount(value);
  if (factor === "aov") return formatVnd(value);
  return formatPercent(value);
}

function formatSignedVnd(value: number): string {
  const rounded = Math.round(value);
  return `${rounded > 0 ? "+" : ""}${formatVnd(rounded)}`;
}

function formatSignedPercent(fraction: number): string {
  const text = formatPercent(fraction);
  return fraction > 0 && text !== "0 %" ? `+${text}` : text;
}

interface GmvCalculatorProps {
  /** `/blog/gmv-la-gi-tiktok-shop` once published; `null` while it is a draft. */
  readonly postHref: string | null;
}

export function GmvCalculator({ postHref }: GmvCalculatorProps) {
  const uid = useId();
  const [mode, setMode] = useState<Mode>("rates");
  const [rates, setRates] = useState<RateInputs>(EMPTY_RATES);
  const [counts, setCounts] = useState<CountInputs>(EMPTY_COUNTS);
  const [errors, setErrors] = useState<Partial<Record<string, string>>>({});
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [isExample, setIsExample] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  // Bumped on every calculation so the what-if controls start fresh for new numbers.
  const [run, setRun] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);

  const fieldId = (key: string) => `${uid}-${mode}-${key}`;

  function show(result: ReturnType<typeof calculateFromRates> | ReturnType<typeof calculateFromCounts>) {
    if (result.ok) {
      setErrors({});
      setFunnel(result.funnel);
      setRun((current) => current + 1);
      setAnnouncement(`Đã tính xong. GMV: ${formatVnd(result.funnel.gmv)}.`);
      return;
    }
    setErrors(result.errors);
    setFunnel(null);
    const count = Object.keys(result.errors).length;
    setAnnouncement(`Chưa tính được: ${count} ô cần sửa.`);
    // Focus the first invalid field, in form order.
    requestAnimationFrame(() => {
      formRef.current?.querySelector<HTMLInputElement>('input[aria-invalid="true"]')?.focus();
    });
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    show(mode === "rates" ? calculateFromRates(rates) : calculateFromCounts(counts));
  }

  function fillExample() {
    setIsExample(true);
    if (mode === "rates") {
      setRates(EXAMPLE_RATES);
      show(calculateFromRates(EXAMPLE_RATES));
    } else {
      setCounts(EXAMPLE_COUNTS);
      show(calculateFromCounts(EXAMPLE_COUNTS));
    }
  }

  function reset() {
    setRates(EMPTY_RATES);
    setCounts(EMPTY_COUNTS);
    setErrors({});
    setFunnel(null);
    setIsExample(false);
    setAnnouncement("Đã xoá số liệu.");
  }

  function switchMode(next: Mode) {
    setMode(next);
    setErrors({});
    setFunnel(null);
    setAnnouncement("");
  }

  function edit(key: string, value: string) {
    setIsExample(false);
    if (mode === "rates") setRates((current) => ({ ...current, [key]: value }));
    else setCounts((current) => ({ ...current, [key]: value }));
    if (errors[key]) setErrors((current) => ({ ...current, [key]: undefined }));
  }

  function renderField<K extends string>(spec: FieldSpec<K>, value: string) {
    const id = fieldId(spec.key);
    const error = errors[spec.key];
    return (
      <div className={styles.field} key={`${mode}-${spec.key}`}>
        <label htmlFor={id}>{spec.label}</label>
        <div className={styles.inputWrap}>
          <input
            aria-describedby={`${id}-hint${error ? ` ${id}-error` : ""}`}
            aria-invalid={error ? true : undefined}
            autoComplete="off"
            id={id}
            inputMode="decimal"
            name={spec.key}
            onChange={(event) => edit(spec.key, event.target.value)}
            spellCheck={false}
            type="text"
            value={value}
          />
          {spec.suffix ? (
            <span aria-hidden="true" className={styles.suffix}>
              {spec.suffix}
            </span>
          ) : null}
        </div>
        <p className={styles.hint} id={`${id}-hint`}>
          {spec.hint}
        </p>
        {error ? (
          <p className={styles.error} id={`${id}-error`}>
            {error}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className={styles.calculator} data-testid="gmv-calculator">
      <form aria-label="Số liệu để tính GMV" className={styles.form} noValidate onSubmit={onSubmit} ref={formRef}>
        <fieldset className={styles.fieldset}>
          <legend>Bạn có số liệu dạng nào?</legend>
          <div className={styles.choices}>
            <label className={styles.choice}>
              <input checked={mode === "rates"} name={`${uid}-mode`} onChange={() => switchMode("rates")} type="radio" />
              Tỷ lệ: CTR, CTOR, AOV
            </label>
            <label className={styles.choice}>
              <input checked={mode === "counts"} name={`${uid}-mode`} onChange={() => switchMode("counts")} type="radio" />
              Số đếm: lượt nhấp, đơn hàng
            </label>
          </div>
        </fieldset>

        {mode === "counts" ? (
          <fieldset className={styles.fieldset}>
            <legend>Bạn có GMV hay AOV?</legend>
            <div className={styles.choices}>
              {(["gmv", "aov"] as const).map((money) => (
                <label className={styles.choice} key={money}>
                  <input
                    checked={counts.money === money}
                    name={`${uid}-money`}
                    onChange={() => {
                      setCounts((current) => ({ ...current, money }));
                      setErrors({});
                      setFunnel(null);
                    }}
                    type="radio"
                  />
                  {money === "gmv" ? "Tôi có GMV" : "Tôi có AOV"}
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}

        <div className={styles.fields}>
          {mode === "rates"
            ? RATE_FIELDS.map((spec) => renderField(spec, rates[spec.key]))
            : [
                ...COUNT_FIELDS.map((spec) => renderField(spec, counts[spec.key])),
                renderField(MONEY_FIELDS[counts.money], counts[counts.money]),
              ]}
        </div>

        <p className={styles.formNote}>
          Lấy mọi số trên cùng một sản phẩm hoặc nhóm sản phẩm, cùng luồng truy cập và cùng khoảng thời gian.
        </p>

        <div className={styles.actions}>
          <Button data-testid="gmv-calculate" type="submit">
            Tính GMV
          </Button>
          <Button data-testid="gmv-example" onClick={fillExample} variant="secondary">
            Thử ví dụ giả định
          </Button>
          <button className={styles.reset} onClick={reset} type="button">
            Xoá số liệu
          </button>
        </div>
      </form>

      <div className={styles.output}>
        <div aria-atomic="true" aria-live="polite" className={styles.live} data-testid="gmv-live" role="status">
          {funnel ? (
            <p className={styles.total}>
              <span className={styles.totalLabel}>GMV</span>
              <span className={styles.totalValue} data-testid="gmv-total">
                {formatVnd(funnel.gmv)}
              </span>
            </p>
          ) : null}
          <span className="ui-visually-hidden">{announcement}</span>
        </div>
        {funnel ? (
          <Results funnel={funnel} isExample={isExample} key={run} postHref={postHref} />
        ) : (
          <div className={styles.empty} data-testid="gmv-empty">
            <p>
              Kết quả hiện ở đây sau khi bạn bấm <strong>Tính GMV</strong>. Chưa có số liệu? Bấm{" "}
              <strong>Thử ví dụ giả định</strong> để xem một ví dụ.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ————— Results ————— */

function PostLink({ postHref, anchor, children }: { postHref: string | null; anchor: GmvPostAnchor; children: ReactNode }) {
  if (!postHref) return null;
  return (
    <a className={styles.link} href={`${postHref}#${GMV_POST_ANCHORS[anchor]}`}>
      {children}
    </a>
  );
}

function Results({ funnel, isExample, postHref }: { funnel: Funnel; isExample: boolean; postHref: string | null }) {
  const [upliftText, setUpliftText] = useState("10");
  const uid = useId();
  const parsedUplift = parseVietnameseNumber(upliftText);
  const upliftValid = parsedUplift.ok && parsedUplift.value > 0 && parsedUplift.value <= 1000;
  const uplift = upliftValid && parsedUplift.ok ? parsedUplift.value : null;
  const upliftLabel = uplift !== null ? `${formatVietnameseNumber(uplift, 2)} %` : "";
  const rows = uplift !== null ? equalUplifts(funnel, uplift) : [];
  const zero = funnel.zeroFactor;

  return (
    <div className={styles.results} data-testid="gmv-results">
      {isExample ? <p className={styles.examplePill}>{EXAMPLE_NOTE}</p> : null}
      {funnel.warnings.map((warning) => (
        <p className={styles.warning} key={warning}>
          {warning}
        </p>
      ))}

      <h3 className={styles.h3}>Phễu từng bước</h3>
      <div className={styles.tableWrap}>
        <table className={styles.table} data-testid="gmv-funnel">
          <caption className="ui-visually-hidden">Phễu GMV từ Lượt hiển thị đến GMV</caption>
          <thead>
            <tr>
              <th scope="col">Bước</th>
              <th scope="col">Tỷ lệ</th>
              <th scope="col">Kết quả</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Lượt hiển thị sản phẩm</th>
              <td />
              <td>{formatCount(funnel.impressions)}</td>
            </tr>
            <tr>
              <th scope="row">Lượt nhấp</th>
              <td>CTR {funnel.ctr === null ? "chưa tính được" : formatPercent(funnel.ctr)}</td>
              <td>{formatCount(funnel.clicks)}</td>
            </tr>
            <tr>
              <th scope="row">Đơn hàng SKU</th>
              <td>CTOR {funnel.ctor === null ? "chưa tính được (chưa có lượt nhấp)" : formatPercent(funnel.ctor)}</td>
              <td>{formatCount(funnel.orders)}</td>
            </tr>
            <tr>
              <th scope="row">GMV</th>
              <td>
                AOV{" "}
                {funnel.aov === null ? (
                  "chưa tính được (chưa có đơn hàng)"
                ) : (
                  <span className={styles.nowrap}>{formatVnd(funnel.aov)}</span>
                )}
              </td>
              <td>{formatVnd(funnel.gmv)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className={styles.small}>
        Số lượt nhấp và đơn hàng được làm tròn để hiển thị; GMV tính từ số chưa làm tròn. GMV theo cách TikTok tính
        gồm cả đơn đã huỷ và hoàn tiền.
      </p>

      <h3 className={styles.h3}>Nếu mỗi bước tăng cùng một mức</h3>
      <div className={styles.field}>
        <label htmlFor={`${uid}-uplift`}>Mức tăng thử cho mỗi bước</label>
        <div className={`${styles.inputWrap} ${styles.inputShort}`}>
          <input
            aria-describedby={upliftValid ? undefined : `${uid}-uplift-error`}
            aria-invalid={upliftValid ? undefined : true}
            autoComplete="off"
            id={`${uid}-uplift`}
            inputMode="decimal"
            onChange={(event) => setUpliftText(event.target.value)}
            type="text"
            value={upliftText}
          />
          <span aria-hidden="true" className={styles.suffix}>
            %
          </span>
        </div>
        {upliftValid ? null : (
          <p className={styles.error} id={`${uid}-uplift-error`}>
            Nhập một mức tăng lớn hơn 0 và không quá 1.000 %, ví dụ 10.
          </p>
        )}
      </div>
      {zero ? (
        <p className={styles.callout} data-testid="gmv-zero">
          GMV đang bằng 0 vì {FACTOR_LABELS[zero]} bằng 0, nên tăng ba chỉ số còn lại không làm GMV tăng. Bước này
          đang chặn cả phễu: hãy xem nó trước.
        </p>
      ) : rows.length > 0 ? (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.table} data-testid="gmv-uplifts">
              <caption className="ui-visually-hidden">GMV khi từng chỉ số tăng {upliftLabel}</caption>
              <thead>
                <tr>
                  <th scope="col">Nếu tăng {upliftLabel}</th>
                  <th scope="col">Từ → thành</th>
                  <th scope="col">GMV mới</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.factor}>
                    <th scope="row">{FACTOR_LABELS[row.factor]}</th>
                    <td>
                      <span className={styles.nowrap}>{formatFactor(row.factor, row.from)}</span> →{" "}
                      <span className={styles.nowrap}>{formatFactor(row.factor, row.to)}</span>
                    </td>
                    <td>
                      {formatVnd(row.gmv)} <span className={styles.gain}>({formatSignedVnd(row.gain)})</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className={styles.small}>
            Bốn dòng cho cùng một GMV, vì GMV là tích của bốn chỉ số. Bảng giữ ba chỉ số còn lại đứng yên; trên thực
            tế chúng ảnh hưởng nhau, ví dụ khi lượt hiển thị tăng mạnh, CTR thường giảm nhẹ.
          </p>
        </>
      ) : null}

      <h3 className={styles.h3}>Bước nào yếu nhất?</h3>
      {zero ? null : (
        <p className={styles.body} data-testid="gmv-weakest">
          Chỉ với một kỳ số liệu, không thể nói CTR {funnel.ctr === null ? "" : `${formatPercent(funnel.ctr)} `}là thấp
          hay cao: TikTok không công bố mức chuẩn chung, và mỗi ngành hàng, mỗi luồng truy cập khác nhau. Trên giấy,
          tăng cùng một mức ở bước nào cũng cho cùng một GMV. Vì vậy bước nên làm trước là bước bạn có thể cải thiện
          nhiều nhất: so từng chỉ số với chính sản phẩm đó ở kỳ trước và với các sản phẩm khác trong shop, trên cùng
          luồng. Bốn câu hỏi dưới đây giúp bạn biết nhìn vào đâu.
        </p>
      )}
      <ul className={styles.guides} data-testid="gmv-guides">
        {STEP_GUIDES.map((guide) => {
          const value = factorValue(funnel, guide.factor);
          const highlighted = zero === guide.factor;
          return (
            <li className={highlighted ? `${styles.guide} ${styles.guideHot}` : styles.guide} key={guide.factor}>
              <p className={styles.guideMeta}>
                {FACTOR_LABELS[guide.factor]}
                {value === null ? "" : `: ${formatFactor(guide.factor, value)}`}
                {highlighted ? " · đang bằng 0" : ""}
              </p>
              <h4 className={styles.h4}>{guide.question}</h4>
              <ul className={styles.lookList}>
                {guide.look.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <PostLink anchor={guide.anchor} postHref={postHref}>
                Cách tăng {FACTOR_LABELS[guide.factor]}
              </PostLink>
            </li>
          );
        })}
      </ul>

      <WhatIf funnel={funnel} />
    </div>
  );
}

function WhatIf({ funnel }: { funnel: Funnel }) {
  const uid = useId();
  const available = FACTOR_ORDER.filter((factor) => factorValue(funnel, factor) !== null);
  const [factor, setFactor] = useState<FactorKey>(available.includes("ctr") ? "ctr" : (available[0] ?? "impressions"));
  const [target, setTarget] = useState("");
  const from = factorValue(funnel, factor);
  const parsed = parseVietnameseNumber(target);
  const unit = factor === "impressions" ? "" : factor === "aov" ? " ₫" : " %";

  let message: ReactNode = (
    <>Nhập giá trị mới để xem GMV thay đổi ra sao, khi ba chỉ số còn lại giữ nguyên.</>
  );
  let invalid = false;
  if (target.trim() !== "") {
    if (!parsed.ok) {
      invalid = true;
      message = "Giá trị mới chưa đúng định dạng số. Ví dụ: 3,6 hoặc 55.000.";
    } else if (factor === "ctr" && parsed.value > 100) {
      invalid = true;
      message = "CTR không thể quá 100 %.";
    } else if (from !== null) {
      const to = factor === "ctr" || factor === "ctor" ? parsed.value / 100 : parsed.value;
      const gmv = gmvWithFactor(funnel, factor, to);
      if (gmv === null) {
        message = "Chưa tính được: phễu còn thiếu một chỉ số (chưa có lượt nhấp hoặc đơn hàng).";
      } else {
        const change = relativeChange(funnel.gmv, gmv);
        message = (
          <>
            Nếu {FACTOR_LABELS[factor]} đổi từ {formatFactor(factor, from)} thành {formatFactor(factor, to)}, GMV đổi
            từ {formatVnd(funnel.gmv)} thành <strong>{formatVnd(gmv)}</strong>
            {change === null ? "" : ` (${formatSignedPercent(change)})`}.
          </>
        );
      }
    }
  }

  return (
    <div className={styles.whatIf}>
      <h3 className={styles.h3}>Thử một thay đổi cụ thể</h3>
      <div className={styles.whatIfFields}>
        <div className={styles.field}>
          <label htmlFor={`${uid}-factor`}>Chỉ số</label>
          <select
            id={`${uid}-factor`}
            onChange={(event) => {
              setFactor(event.target.value as FactorKey);
              setTarget("");
            }}
            value={factor}
          >
            {available.map((key) => (
              <option key={key} value={key}>
                {FACTOR_LABELS[key]}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.field}>
          <label htmlFor={`${uid}-target`}>Giá trị mới{unit ? ` (${unit.trim()})` : ""}</label>
          <div className={styles.inputWrap}>
            <input
              aria-describedby={`${uid}-whatif-result`}
              aria-invalid={invalid ? true : undefined}
              autoComplete="off"
              id={`${uid}-target`}
              inputMode="decimal"
              onChange={(event) => setTarget(event.target.value)}
              placeholder={from === null ? "" : formatFactor(factor, from).replace(/ (%|₫)$/, "")}
              type="text"
              value={target}
            />
            {unit ? (
              <span aria-hidden="true" className={styles.suffix}>
                {unit.trim()}
              </span>
            ) : null}
          </div>
        </div>
      </div>
      <p
        aria-live="polite"
        className={invalid ? styles.error : styles.body}
        data-testid="gmv-whatif"
        id={`${uid}-whatif-result`}
      >
        {message}
      </p>
    </div>
  );
}
