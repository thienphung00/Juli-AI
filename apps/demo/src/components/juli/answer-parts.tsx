"use client";

import { useState } from "react";
import type {
  JuliChoiceOption,
  JuliDataAnswerData,
  JuliLabelData,
  JuliNeedsChoiceData,
  JuliPathStep,
  JuliTemplate,
  JuliUnsupportedData,
} from "@juli/contracts";

import { juliHref } from "../../lib/juli/links";
import { Delta } from "./delta";

export type JuliPlatform = "shopee" | "tiktok";

/** U4b: the path row, one link per step. Vertical list on mobile (CSS). */
export function PathRow({ steps, platform }: { readonly steps: readonly JuliPathStep[]; readonly platform: JuliPlatform }) {
  return (
    <nav aria-label="Đường phân tích" className="juli-path">
      <ol>
        {steps.map((step, i) => (
          <li key={`${step.label_vi}-${i}`}>
            <a className="juli-pill" href={juliHref(step.link, platform)}>
              <span>{step.label_vi}</span>
              {step.delta ? <Delta delta={step.delta} /> : step.value_vi ? <span className="juli-num">· {step.value_vi}</span> : null}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** U4c: a stop label, never a paragraph. */
export function StopLabel({ label }: { readonly label: JuliLabelData }) {
  return (
    <div className="juli-label-wrap">
      <span className={`juli-label juli-label--${label.stop_reason}`} data-reason={label.stop_reason}>
        {label.text_vi}
      </span>
      {label.detail_vi ? (
        <div className="juli-label-detail">
          {label.detail_vi.split("\n").map((line) => (
            <span key={line}>{line}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

const MAX_BAR_POINTS = 60;

function DailyBars({ data }: { readonly data: JuliDataAnswerData }) {
  const [table, setTable] = useState(false);
  const [picked, setPicked] = useState<number | null>(null);
  const series = (data.series ?? []).slice(0, MAX_BAR_POINTS);
  const max = Math.max(1, ...series.map((p) => p.value));
  const top = series.reduce<(typeof series)[number] | null>((best, p) => (!p.missing && (!best || p.value > best.value) ? p : best), null);
  return (
    <div className="juli-daily">
      {table ? (
        <div className="juli-table-scroll">
          <table className="juli-table">
            <thead>
              <tr>
                <th scope="col">Ngày</th>
                <th scope="col" className="juli-right">
                  {data.title_vi}
                </th>
              </tr>
            </thead>
            <tbody>
              {series.map((p) => (
                <tr key={p.label_vi}>
                  <td>{p.label_vi}</td>
                  <td className="juli-num juli-right">{p.missing ? "thiếu dữ liệu" : p.value_vi}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="juli-bars" role="group" aria-label={`${data.title_vi} ${data.window_vi}`}>
          {series.map((p, i) => (
            <button
              key={p.label_vi}
              type="button"
              className="juli-bar"
              aria-label={`${p.label_vi}: ${p.missing ? "thiếu dữ liệu" : p.value_vi}`}
              aria-pressed={picked === i}
              title={`${p.label_vi}: ${p.value_vi}`}
              onClick={() => setPicked(picked === i ? null : i)}
            >
              <i
                className={p.missing ? "juli-bar__fill juli-bar__fill--missing" : "juli-bar__fill"}
                style={{ height: p.missing ? "2px" : `${Math.max(2, Math.round((p.value / max) * 100))}%` }}
              />
              <span>{p.label_vi}</span>
            </button>
          ))}
        </div>
      )}
      <div className="juli-daily__foot">
        <span className="juli-num" aria-live="polite">
          {picked !== null && series[picked]
            ? `${series[picked]!.label_vi} · ${series[picked]!.missing ? "thiếu dữ liệu" : series[picked]!.value_vi}`
            : top
              ? `Cao nhất ${top.label_vi} · ${top.value_vi}`
              : ""}
        </span>
        <button type="button" className="juli-link-button" onClick={() => setTable((v) => !v)}>
          {table ? "Xem biểu đồ" : "Xem bảng"}
        </button>
      </div>
    </div>
  );
}

/** U4a: one data answer. */
export function DataAnswer({ data, platform }: { readonly data: JuliDataAnswerData; readonly platform: JuliPlatform }) {
  return (
    <section className={`juli-data juli-data--${data.kind}`} aria-label={data.title_vi}>
      {data.kind === "metric_total" ? (
        <>
          <div className="juli-kpi-row">
            <span className="juli-kpi juli-num">{data.value}</span>
            {data.delta ? <Delta delta={data.delta} chip /> : null}
          </div>
          <p className="juli-p">{data.window_vi}</p>
        </>
      ) : null}
      {data.kind === "top_products" ? (
        <ol className="juli-top">
          {(data.rows ?? []).map((row, i) => (
            <li key={`${row.label_vi}-${i}`} className="juli-top__row">
              <span className="juli-rank juli-num">{i + 1}</span>
              {row.link ? <a href={juliHref(row.link, platform)}>{row.label_vi}</a> : <span>{row.label_vi}</span>}
              <span className="juli-num">{row.value_vi}</span>
            </li>
          ))}
        </ol>
      ) : null}
      {data.kind === "daily_trend" ? <DailyBars data={data} /> : null}
      {data.kind === "channel_breakdown" ? (
        <div className="juli-table-scroll">
          <table className="juli-table">
            <thead>
              <tr>
                <th scope="col">Kênh</th>
                <th scope="col" className="juli-right">
                  {data.title_vi.replace(/ theo kênh$/, "")}
                </th>
              </tr>
            </thead>
            <tbody>
              {(data.rows ?? []).map((row, i) => (
                <tr key={`${row.label_vi}-${i}`}>
                  <td>
                    {row.link ? <a href={juliHref(row.link, platform)}>{row.label_vi}</a> : row.label_vi}
                    {row.missing ? <span className="juli-miss">thiếu dữ liệu</span> : null}
                  </td>
                  <td className="juli-num juli-right">{row.value_vi}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <div className="juli-fresh">{data.fresh_vi}</div>
    </section>
  );
}

/** U5a: one short question + buttons + "Khác…". */
export function NeedsChoice({
  data,
  interactive,
  templates,
  onChoose,
  onOther,
  onTemplate,
}: {
  readonly data: JuliNeedsChoiceData;
  readonly interactive: boolean;
  readonly templates: readonly JuliTemplate[];
  readonly onChoose: (item: string, option: JuliChoiceOption) => void;
  readonly onOther: () => void;
  readonly onTemplate: (template: JuliTemplate) => void;
}) {
  if (data.item === "template") {
    // Jev outage (J11): the options are the template keys; render them as the template buttons.
    return (
      <div className="juli-choice">
        <p className="juli-ask">{data.question_vi}</p>
        <div className="juli-opts" role="group" aria-label="Mẫu câu hỏi">
          {data.options.map((o) => {
            const template = templates.find((t) => t.key === o.value) ?? { key: o.value, label_vi: o.label_vi };
            return (
              <button key={o.value} type="button" className="juli-opt" disabled={!interactive} onClick={() => onTemplate(template)}>
                {template.label_vi}
              </button>
            );
          })}
        </div>
      </div>
    );
  }
  const stacked = data.item === "product";
  return (
    <div className="juli-choice">
      <p className="juli-ask">{data.question_vi}</p>
      <div className={`juli-opts${stacked ? " juli-opts--stack" : ""}`} role="group" aria-label={data.question_vi}>
        {data.options.map((o) => (
          <button key={o.value} type="button" className="juli-opt" disabled={!interactive} onClick={() => onChoose(data.item, o)}>
            {o.label_vi}
          </button>
        ))}
        <button type="button" className="juli-opt juli-opt--other" disabled={!interactive} onClick={onOther}>
          Khác…
        </button>
      </div>
    </div>
  );
}

/** U5b / U5c: fixed line + template buttons + the platform switch. */
export function Unsupported({
  data,
  templates,
  interactive,
  onTemplate,
  onSwitchPlatform,
}: {
  readonly data: JuliUnsupportedData;
  readonly templates: readonly JuliTemplate[];
  readonly interactive: boolean;
  readonly onTemplate: (template: JuliTemplate) => void;
  readonly onSwitchPlatform?: (platform: "tiktok" | "shopee") => void;
}) {
  const shown = data.templates.map((key) => templates.find((t) => t.key === key)).filter((t): t is JuliTemplate => Boolean(t));
  const switchTo = data.switch_platform;
  return (
    <div className="juli-choice">
      <p className="juli-ask">{data.text_vi}</p>
      <div className="juli-opts" role="group" aria-label="Mẫu câu hỏi">
        {switchTo && onSwitchPlatform ? (
          <button type="button" className="juli-opt juli-opt--primary" onClick={() => onSwitchPlatform(switchTo)}>
            {switchTo === "tiktok" ? "Chuyển sang shop TikTok" : "Chuyển sang shop Shopee"}
          </button>
        ) : null}
        {shown.map((t) => (
          <button key={t.key} type="button" className="juli-opt" disabled={!interactive} onClick={() => onTemplate(t)}>
            {t.label_vi}
          </button>
        ))}
      </div>
    </div>
  );
}
