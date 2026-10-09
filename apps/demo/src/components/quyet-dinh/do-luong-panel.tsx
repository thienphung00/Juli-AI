"use client";

import type { WorkflowRunListItem } from "@juli/contracts";
import { useState } from "react";

import type { CardView } from "../../lib/quyet-dinh/card-model";
import { MEASURE_NO_READING, MEASURE_WAITING, bandMetricLabel } from "../../lib/quyet-dinh/copy";
import {
  MEASURE_TABS,
  bandRows,
  breachSentence,
  day14Steps,
  day7Steps,
  finalBox,
  measureHead,
  resultRows,
  tabOfStage,
  targetBlock,
  waitingLine,
  type MeasureStep,
  type MeasureTab,
} from "../../lib/quyet-dinh/measure-model";
import { fullDate } from "../../lib/quyet-dinh/p10-format";
import type { Measurement } from "../../lib/quyet-dinh/p10-types";
import type { ReasonChoice } from "../../lib/quyet-dinh/reasons";
import { addDays, vnDate } from "../../lib/quyet-dinh/timeline";
import type { RevertQuestion, RunChanges } from "../../lib/quyet-dinh/types";
import { num } from "../../lib/vn-format";
import { ReasonDialog, revertDialogBody } from "./reason-dialog";
import { ConflictBox } from "./run-panel";
import { StepList, type StepRow } from "./run-steps";

/**
 * Đo lường (ADR-109 Amendment 1 d.6; `Measure.dc.html`, `Day7.dc.html`,
 * `Day14.dc.html`). Tabs Ngày 0 / Ngày 7 · kiểm tra / Ngày 14 · chốt hold
 * each measured run at its `measurement.stage` (contract §6). A run panel:
 * the target and the allowed band, then per stage the waiting line, the
 * day-7 check (within → nothing to do; outside → "Hoàn tác?") or the day-14
 * verdict. Until P10-B's measurement endpoint exists a run shows the
 * completion-based waiting line (P8-F behaviour).
 */

export type ChangesState =
  | { readonly status: "loading" }
  | { readonly status: "error" }
  | { readonly status: "ready"; readonly changes: RunChanges };

export type MeasurementState =
  | { readonly status: "loading" }
  | { readonly status: "error" }
  | { readonly status: "ready"; readonly measurement: Measurement | null };

export interface RevertActionState {
  readonly busy: boolean;
  readonly error: string | null;
  readonly conflict: string | null;
  readonly revertRunId: string | null;
  readonly kept: boolean;
}

export const IDLE_REVERT: RevertActionState = { busy: false, error: null, conflict: null, revertRunId: null, kept: false };

/** A run that finished normally (it may have written); revert runs drop out once their changes load. */
export function isExecutedRun(run: WorkflowRunListItem): boolean {
  return run.status === "completed" && run.stop_reason === "final_response";
}

export function measurementLine(completedAt: string | null, nowMs: number | null): string {
  if (!completedAt) return MEASURE_NO_READING;
  const day7 = addDays(completedAt, 7);
  if (!day7) return MEASURE_NO_READING;
  if (nowMs === null || nowMs < Date.parse(day7)) return MEASURE_WAITING(vnDate(day7));
  return MEASURE_NO_READING;
}

/** A P8 day-7 breach (no measurement endpoint yet): "CTR lệch −4,8 % (ngưỡng ±3 %)". */
export function breachLine(breach: RevertQuestion["breaches"][number]): string {
  const sign = breach.impact_pct >= 0 ? "+" : "−";
  return `${bandMetricLabel(breach.metric)} lệch ${sign}${num(Math.abs(breach.impact_pct), 1)} % (ngưỡng ±${num(breach.band_pct, breach.band_pct % 1 ? 1 : 0)} %)`;
}

export interface MeasureItem {
  readonly run: WorkflowRunListItem;
  readonly card: CardView | null;
  readonly changes: ChangesState | undefined;
  readonly measurement: MeasurementState | undefined;
  readonly question: RevertQuestion | null;
  readonly action: RevertActionState;
}

export function itemTab(item: MeasureItem): MeasureTab {
  return item.measurement?.status === "ready" && item.measurement.measurement
    ? tabOfStage(item.measurement.measurement.stage)
    : "d0";
}

export function measureTitle(items: readonly MeasureItem[], tab: MeasureTab): string {
  const first = items.find((item) => itemTab(item) === tab);
  const m = first?.measurement?.status === "ready" ? first.measurement.measurement : null;
  if (m) return measureHead(m).headline;
  if (tab === "d0") return "Đang chờ dữ liệu sau khi áp dụng";
  if (tab === "d7") return "Ngày 7: kiểm tra sơ bộ";
  return "Ngày 14: kết quả đã chốt";
}

export function defaultTab(items: readonly MeasureItem[]): MeasureTab {
  const tabs = items.map(itemTab);
  if (tabs.includes("d7")) return "d7";
  if (tabs.includes("d0")) return "d0";
  if (tabs.includes("d14")) return "d14";
  return "d0";
}

export function DoLuongPanel({
  items,
  tab,
  nowMs,
  onTab,
  onRevert,
  onKeep,
  onOpenRun,
  proposalsHref,
  onOpenProposals,
}: {
  readonly items: readonly MeasureItem[];
  readonly tab: MeasureTab;
  readonly nowMs: number | null;
  readonly onTab: (tab: MeasureTab) => void;
  readonly onRevert: (item: MeasureItem, choice: ReasonChoice) => void;
  readonly onKeep: (item: MeasureItem) => void;
  readonly onOpenRun: (runId: string) => void;
  readonly proposalsHref: string;
  readonly onOpenProposals: (event: React.MouseEvent<HTMLAnchorElement>) => void;
}) {
  const visible = items.filter((item) => itemTab(item) === tab);
  return (
    <div className="qv-dl">
      <div aria-label="Mốc đo" className="qv-mtabs" role="tablist">
        {MEASURE_TABS.map((entry) => (
          <button
            aria-selected={entry.id === tab}
            className="qv-mtab"
            key={entry.id}
            onClick={() => onTab(entry.id)}
            role="tab"
            type="button"
          >
            {entry.label}
          </button>
        ))}
      </div>
      {items.length === 0 ? (
        <div className="qv-empty" data-testid="measure-list">
          <p>Chưa có lượt chạy nào ghi thay đổi lên TikTok Shop.</p>
        </div>
      ) : visible.length === 0 ? (
        <div className="qv-empty" data-testid="measure-list">
          <p>Chưa có thay đổi nào ở mốc này.</p>
        </div>
      ) : (
        <div className="qv-dl" data-testid="measure-list">
          {visible.map((item) => (
            <MeasurePanel
              item={item}
              key={item.run.id}
              nowMs={nowMs}
              onKeep={() => onKeep(item)}
              onOpenProposals={onOpenProposals}
              onOpenRun={onOpenRun}
              onRevert={(choice) => onRevert(item, choice)}
              proposalsHref={proposalsHref}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function measureRows(steps: readonly MeasureStep[]): StepRow[] {
  return steps.map((step, index) => ({
    key: String(index),
    label: step.label,
    status: step.status,
    result: step.result,
    time: step.status === "upcoming" ? "" : step.time,
  }));
}

function MeasurePanel({
  item,
  nowMs,
  onRevert,
  onKeep,
  onOpenRun,
  proposalsHref,
  onOpenProposals,
}: {
  readonly item: MeasureItem;
  readonly nowMs: number | null;
  readonly onRevert: (choice: ReasonChoice) => void;
  readonly onKeep: () => void;
  readonly onOpenRun: (runId: string) => void;
  readonly proposalsHref: string;
  readonly onOpenProposals: (event: React.MouseEvent<HTMLAnchorElement>) => void;
}) {
  const { run, card, action } = item;
  const [expanded, setExpanded] = useState(true);
  const [dialog, setDialog] = useState(false);
  const m = item.measurement?.status === "ready" ? item.measurement.measurement : null;
  const changes = item.changes?.status === "ready" ? item.changes.changes : null;
  const labels = changes && changes.changes.length > 0 ? changes.changes.map((c) => c.label) : (card?.changeLabels ?? []);
  const head = m ? measureHead(m) : null;
  const chip = head?.chip ?? { label: "Chờ đo · ngày 0", tone: "muted" as const };
  const workflow = card?.meta.split(" · ")[0] ?? "Tối ưu sản phẩm";
  const sub = [workflow, `Thay đổi vào ${fullDate(run.completed_at)}`, labels.length > 0 ? `Đã đổi ${labels.join(", ")}` : null]
    .filter(Boolean)
    .join(" · ");
  const canRevert =
    card?.executor !== "seller_center" && (changes ? changes.revert.available && !changes.reverts_run_id : true);
  const headingId = `measure-${run.id}`;
  const outside = m?.stage === "day7" && m.day7 !== null && !m.day7.within_band;
  const answered: "revert" | "keep" | null = action.revertRunId ? "revert" : action.kept ? "keep" : null;
  const box = m ? finalBox(m, card?.leverLabel ?? null) : null;
  const waiting = !m || m.stage === "waiting";
  const day7Iso = run.completed_at ? addDays(run.completed_at, 7) : null;
  const pastDay7 = !m && day7Iso !== null && nowMs !== null && nowMs >= Date.parse(day7Iso);

  return (
    <section aria-labelledby={headingId} className="qv-run qv-measure" data-run-id={run.id} data-testid="measure-panel">
      <div className="qv-measure__head">
        <div className="qv-card__id">
          <div className="qv-card__name-row">
            {card?.sku ? <span className="qv-sku">SKU · {card.sku}</span> : null}
            <h2 className="qv-run__title" id={headingId}>
              {card?.title ?? run.product_name}
            </h2>
          </div>
          <div className="qv-card__meta">{sub}</div>
        </div>
        <div className="qv-measure__right">
          <span className={`qv-chip qv-tone--${chip.tone}`} data-testid="measure-chip">
            {chip.label}
          </span>
          <button aria-expanded={expanded} className="qv-toggle" onClick={() => setExpanded((v) => !v)} type="button">
            {expanded ? "Thu gọn" : "Mở rộng"}
          </button>
        </div>
      </div>

      {expanded ? (
        <div className="qv-run__body">
          {m ? <TargetAndBands m={m} /> : null}

          {m?.stage === "day7" ? <StepList label="Các bước kiểm tra ngày 7" rows={measureRows(day7Steps(m, answered))} testId="day7-steps" wide /> : null}
          {m?.stage === "final" ? (
            <StepList label="Các bước chốt ngày 14" rows={measureRows(day14Steps(m, card?.leverLabel ?? null))} testId="day14-steps" wide />
          ) : null}

          {waiting ? (
            <div className="qv-grey qv-grey--measure" data-testid="measure-waiting">
              {m ? waitingLine(m, null) : pastDay7 ? MEASURE_NO_READING : waitingLine(null, day7Iso)}
            </div>
          ) : null}

          {m && !waiting && m.rows.length > 0 ? <ResultTable m={m} /> : null}

          {outside && !answered ? (
            <div className="qv-orange qv-ask" data-testid="day7-ask">
              <div className="qv-orange__title">Hoàn tác?</div>
              <div className="qv-orange__text">
                {breachSentence(m)} Juli không tự hoàn tác — bạn quyết định.
              </div>
              <div className="qv-buttons">
                {canRevert ? (
                  <button className="qv-btn qv-btn--primary" disabled={action.busy} onClick={() => setDialog(true)} type="button">
                    Hoàn tác
                  </button>
                ) : null}
                <button className="qv-btn qv-btn--secondary" disabled={action.busy} onClick={onKeep} type="button">
                  Giữ thay đổi
                </button>
              </div>
              <div className="qv-note">
                {canRevert
                  ? `Hoàn tác tạo một lượt chạy mới khôi phục ${labels.join(" và ") || "nội dung"} cũ, cũng qua bước xác nhận.`
                  : "Với khuyến mãi (Seller Center): Hoàn tác = Juli hướng dẫn bạn tắt khuyến mãi."}
              </div>
            </div>
          ) : null}

          {!m && item.question && !answered ? (
            <div className="qv-orange qv-ask" data-testid="day7-ask">
              <div className="qv-orange__title">Hoàn tác?</div>
              <div className="qv-orange__text">
                {item.question.breaches.map(breachLine).join(" · ")}. Juli không tự hoàn tác — bạn quyết định.
              </div>
              <div className="qv-buttons">
                {canRevert ? (
                  <button className="qv-btn qv-btn--primary" disabled={action.busy} onClick={() => setDialog(true)} type="button">
                    Hoàn tác
                  </button>
                ) : null}
                <button className="qv-btn qv-btn--secondary" disabled={action.busy} onClick={onKeep} type="button">
                  Giữ thay đổi
                </button>
              </div>
            </div>
          ) : null}

          {action.revertRunId ? (
            <div className="qv-reverted" role="status">
              <span>
                Đã tạo lượt chạy hoàn tác: khôi phục {labels.join(" và ") || "nội dung"} cũ, bạn xác nhận trước khi Juli ghi. Kết quả đo
                của thay đổi này dừng lại.
              </span>
              <a
                className="qv-link"
                href={`/decisions?tab=dang-thuc-hien&run=${action.revertRunId}`}
                onClick={(event) => {
                  event.preventDefault();
                  onOpenRun(action.revertRunId!);
                }}
              >
                Xem ở Đang thực hiện ›
              </a>
            </div>
          ) : null}
          {action.kept ? (
            <div className="qv-grey" role="status">
              Bạn giữ thay đổi. Juli tiếp tục đo tới ngày 14
              {outside && m ? ` và ghi chú ${m.rows.find((r) => r.tone === "warn")?.label ?? "chỉ số"} đã ra ngoài khoảng ở ngày 7` : ""}.
            </div>
          ) : null}
          {action.conflict ? <ConflictBox message={action.conflict} /> : null}
          {action.error ? (
            <p className="qv-inline-error" role="alert">
              {action.error}
            </p>
          ) : null}

          {box ? (
            <div className={`qv-final qv-final--${box.tone}`} data-testid="final-box">
              <div className="qv-final__title">{box.title}</div>
              <div className="qv-final__body">{box.body}</div>
              <div className="qv-final__actions">
                <a className="qv-link" href={proposalsHref} onClick={onOpenProposals}>
                  {box.next}
                </a>
                {box.offerRevert && canRevert && !action.revertRunId ? (
                  <button className="qv-btn qv-btn--secondary" disabled={action.busy} onClick={() => setDialog(true)} type="button">
                    Hoàn tác
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}

          {(waiting || (m?.stage === "day7" && !outside)) && canRevert && !action.revertRunId ? (
            <div className="qv-measure__foot">
              <button className="qv-btn qv-btn--secondary" disabled={action.busy} onClick={() => setDialog(true)} type="button">
                Hoàn tác
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      <ReasonDialog
        body={revertDialogBody(labels, card?.title ?? run.product_name)}
        mode="revert"
        onCancel={() => setDialog(false)}
        onSubmit={(choice) => {
          setDialog(false);
          onRevert(choice);
        }}
        open={dialog}
      />
    </section>
  );
}

function TargetAndBands({ m }: { readonly m: Measurement }) {
  const target = targetBlock(m);
  const bands = bandRows(m);
  return (
    <div className="qv-target" data-testid="measure-target">
      <div className="qv-target__head">
        <span className="qv-target__title">Mục tiêu và ngưỡng dao động</span>
        <span className="qv-target__hint">Trung bình mỗi ngày · so với 14 ngày trước khi áp dụng</span>
      </div>
      <div className="qv-target__cards">
        <div className="qv-target__card">
          <span className="qv-target__label">{target.label}</span>
          <span className="qv-target__value">{target.pair}</span>
          <span className="qv-target__note">{target.note}</span>
        </div>
        {target.gmv ? (
          <div className="qv-target__card qv-target__card--gmv">
            <span className="qv-target__label">GMV dự kiến</span>
            <span className="qv-target__value">{target.gmv}</span>
          </div>
        ) : null}
      </div>
      {bands.length > 0 ? (
        <div className="qv-table-wrap">
          <table className="qv-bands">
            <thead>
              <tr>
                <th scope="col">Chỉ số không được lệch</th>
                <th scope="col">Trước</th>
                <th scope="col">Ngưỡng bạn đặt</th>
                <th scope="col">Được phép dao động trong</th>
              </tr>
            </thead>
            <tbody>
              {bands.map((band) => (
                <tr key={band.key}>
                  <td>{band.label}</td>
                  <td>{band.before}</td>
                  <td>{band.band}</td>
                  <td>{band.range}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function ResultTable({ m }: { readonly m: Measurement }) {
  const rows = resultRows(m);
  return (
    <div className="qv-table-wrap">
      <table className="qv-results" data-testid="measure-results">
        <thead>
          <tr>
            <th scope="col">Chỉ số</th>
            <th scope="col">Trước</th>
            <th scope="col">Mục tiêu / khoảng cho phép</th>
            <th scope="col">Thực tế</th>
            <th scope="col">Đánh giá</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>{row.name}</td>
              <td>{row.before}</td>
              <td>{row.expected}</td>
              <td>{row.actual}</td>
              <td>
                <span className={`qv-verdict qv-verdict--${row.tone}`}>{row.verdict}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
