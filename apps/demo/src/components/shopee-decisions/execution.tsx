"use client";

import { useEffect, useRef, useState } from "react";

import { DASH, fmt } from "../../lib/shopee-analytics/format";
import { shopeeImageSrc } from "../../lib/shopee-analytics/image-src";
import { useSampleShopReviewer } from "../../lib/reviewer/mode";
import { useReco } from "../../lib/shopee-decisions/context";
import { READBACK_LABEL, countdownOf, readbackOf, readingsOf, stepText, vnWhen, type Readback } from "../../lib/shopee-decisions/model";
import type { CardDetail, ExecutionSheet, ExecutionStep, SheetPage } from "../../lib/shopee-decisions/types";
import { capturedVoucherId, FILL_JOB_KINDS, FillJobsChecklist, fillJobHref, isForwardJob, isRevertJob, ListingSheetExtras, useFillJobs, type FillJobRow } from "../planned-changes/listing-extras";
import { TextChip } from "../shopee-analytics/ui";
import { jobHref, jobWord, jobDiffLines, markDoneBody, type CardJob } from "../../lib/shopee-decisions/card-job";
import { CopyButton, errorText } from "./ui";

/**
 * Assisted execution (p90-plan "Assisted execution"): Juli never writes to Seller Centre. An
 * approved card shows the sheet - the page, each field with its exact before -> after (with copy
 * buttons) and the time window - and a link to open the page. A person saves it with Shopee's own
 * button, then marks "Đã làm"; the Connector's next readings say Chờ xác minh / Đã xác minh /
 * Không khớp / Chưa thấy, and the 14 / 28-day measurement starts when the change is verified.
 * "Hoàn tác" (executed cards) shows the same steps in reverse; "Đã hoàn tác" records the revert.
 */

/** K4: the current job's status word (Chờ điền / Đã điền · chờ bạn lưu / Đã lưu · chờ xác minh / Khớp / Lệch), its count and the differing fields. */
export function JobLine({ job }: { readonly job: CardJob }) {
  const diffs = jobDiffLines(job);
  const tone = job.readback?.result === "match" ? "up" : job.readback?.result === "mismatch" ? "down" : job.status === "filled" ? "warn" : "flat";
  return (
    <div className="sd-job" data-testid="sd-job">
      <TextChip tone={tone}>{jobWord(job)}</TextChip>
      {job.total > 0 ? <span data-testid="sd-job-count">{`${job.filled}/${job.total} đã điền`}</span> : null}
      {diffs.length > 0 ? (
        <ul data-testid="sd-job-diffs">
          {diffs.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export const READ_ONLY_TITLE = "Chế độ xem: không thể thao tác thay seller";

/**
 * The page of a sheet: its name and ONE button. "Mở và điền" when the Connector has a fill job
 * (`fillHref` carries the job), else "Mở trang". A page with no known address shows only its name.
 */
export function PageLink({ page, fillHref, reverse = false }: { readonly page: SheetPage; readonly fillHref?: string | null; readonly reverse?: boolean }) {
  // P100 S2-D4: the sample shop is not in Seller Centre, so its sheet names the page without a link.
  const sample = useSampleShopReviewer();
  // an undo never links to the forward create page: only the revert job's own page opens
  const href = sample ? null : (fillHref ?? (reverse ? null : page.deep_link));
  return (
    <span className="sd-page" data-testid="sd-page">
      <b>{page.label}</b>
      {href ? (
        <a className="sa-btn sa-btn--primary sa-btn--s" data-testid="sd-page-open" href={href} rel="noopener noreferrer" target="_blank">
          {fillHref ? "Mở và điền" : "Mở trang"}
        </a>
      ) : null}
    </span>
  );
}

const COVER_BEFORE = /^(Ảnh bìa hiện tại(?: \([^)]*\))?):\s*(.+)$/;

/** The cover step's "before" names the image by its path; show the picture (or just the label), never the path. */
function BeforeCell({ step }: { readonly step: ExecutionStep }) {
  const text = stepText(step.before, step.unit);
  const m = typeof step.before === "string" ? COVER_BEFORE.exec(step.before.trim()) : null;
  if (!m) return <span className="sd-step__before">{text}</span>;
  const src = shopeeImageSrc(m[2]);
  return (
    <span className="sd-step__before">
      {m[1]}
      {src ? (
        <>
          {" "}
          {/* eslint-disable-next-line @next/next/no-img-element -- seller image URLs, not optimisable assets */}
          <img alt="Ảnh bìa hiện tại" data-testid="sd-step-cover" src={src} style={{ width: 40, height: 40, objectFit: "cover", borderRadius: 4, verticalAlign: "middle" }} />
        </>
      ) : null}
    </span>
  );
}

/** A revert step whose original value is known to nobody: say which field. */
export const NO_BEFORE = "Chưa có giá trị cũ";

function StepRow({ step, reverse }: { readonly step: ExecutionStep; readonly reverse: boolean }) {
  if (step.action) {
    return (
      <li className="sd-step" data-testid={`sd-step-${step.order}`}>
        <span className="sd-step__n">{step.order}</span>
        <span className="sd-step__field">
          <b>{step.field}</b>
        </span>
        <span className="sd-step__after">{step.action}</span>
      </li>
    );
  }
  const unknown = reverse && (step.after === null || step.after === undefined || step.after === "");
  return (
    <li className="sd-step" data-testid={`sd-step-${step.order}`}>
      <span className="sd-step__n">{step.order}</span>
      <span className="sd-step__field">
        <b>{step.field}</b>
        {step.page ? <PageLink page={step.page} /> : null}
        {step.starts ? <span className="sa-hint">Bật lúc {vnWhen(step.starts)}</span> : null}
      </span>
      <BeforeCell step={step} />
      <span aria-hidden="true">→</span>
      {unknown ? (
        <b className="sd-step__after sd-step__after--unknown" data-testid={`sd-step-unknown-${step.order}`}>
          {NO_BEFORE}
        </b>
      ) : (
        <b className="sd-step__after">
          {stepText(step.after, step.unit)}
          {reverse && step.before_source === "connector" ? <TextChip tone="info">Connector đã đọc</TextChip> : null}
        </b>
      )}
      {step.copy ? <CopyButton label={step.field} text={step.copy} /> : <span />}
    </li>
  );
}

/** The revert's own warning: the fields whose original value is known to nobody (never a silent "—"). */
export function UnknownBefore({ sheet }: { readonly sheet: ExecutionSheet }) {
  const missing = sheet.unknown_before ?? [];
  if (missing.length === 0) return null;
  return (
    <p className="sd-error" data-testid="sd-revert-unknown" role="note">
      Chưa có giá trị cũ của: {missing.join(", ")}. Nhập lại giá trị cũ bạn biết, Juli không đoán.
    </p>
  );
}

export function SheetView({ sheet, reverse = false, fillHref = null }: { readonly sheet: ExecutionSheet; readonly reverse?: boolean; readonly fillHref?: string | null }) {
  const steps = reverse ? sheet.revert_steps : sheet.steps;
  const w = sheet.time_window;
  return (
    <div className="sd-sheet" data-testid={reverse ? "sd-revert-sheet" : "sd-sheet"}>
      <PageLink fillHref={fillHref} page={sheet.page} reverse={reverse} />
      <ol className="sd-steps">
        {steps.map((s) => (
          <StepRow key={s.order} reverse={reverse} step={s} />
        ))}
      </ol>
      {reverse ? <UnknownBefore sheet={sheet} /> : null}
      {reverse ? null : (
        <p className="sa-hint" data-testid="sd-time-window">
          Thời gian: {w.start ?? DASH}
          {typeof w.days === "number" ? ` · chạy ${fmt(w.days, 0)} ngày` : ""}
        </p>
      )}
      {reverse ? null : (
        <p className="sa-hint" data-testid="sd-save-hint">
          {sheet.save_hint}
        </p>
      )}
    </div>
  );
}

const READBACK_TONE = { pending: "warn", verified: "up", mismatch: "down", not_seen: "warn", none: "flat" } as const;

function ReadbackBlock({ rb, deadline }: { readonly rb: Readback; readonly deadline: number }) {
  const sample = useSampleShopReviewer();
  if (rb.state === "none") return null;
  return (
    <div className={`sd-readback sd-readback--${rb.state}`} data-testid="sd-readback">
      <TextChip tone={READBACK_TONE[rb.state]}>{READBACK_LABEL[rb.state]}</TextChip>
      <span>
        {rb.state === "pending" && sample ? "Juli đọc lại Seller Centre để xác minh." : null}
        {rb.state === "pending" && !sample ? `Juli đọc lại ở lần chạy kế tiếp của Connector; chưa thấy sau ${deadline} giờ sẽ báo cho Ops.` : null}
        {rb.state === "verified" ? `Giá trị đọc được: ${rb.observed ?? DASH} · lúc ${vnWhen(rb.observedAt)}. Đồng hồ đo lường chạy từ lúc này.` : null}
        {rb.state === "mismatch" ? `Giá trị đọc được: ${rb.observed ?? DASH}, khác giá trị đã đề xuất. Kiểm tra lại trên Seller Centre hoặc báo cho Ops.` : null}
        {rb.state === "not_seen" ? `Chưa thấy thay đổi trên Seller Centre sau ${deadline} giờ. Kiểm tra bạn đã bấm Lưu chưa.` : null}
      </span>
    </div>
  );
}

function Measurement({ detail, rb }: { readonly detail: CardDetail; readonly rb: Readback }) {
  const { now } = useReco();
  const plan = detail.card.measurement_plan;
  const cd = countdownOf(plan.planned_days, rb, (now ?? (() => new Date()))());
  const { t7, final } = readingsOf(detail.journey);
  const reading = (r: NonNullable<typeof t7>) => (
    <li data-testid={`sd-reading-${r.label === "Ngày 7" ? "t7" : "final"}`} key={r.label}>
      <b>{r.label}</b>: {r.impactPct === null ? `chưa kết luận${r.reason ? ` (${r.reason})` : ""}` : `${r.impactPct >= 0 ? "+" : "−"}${fmt(Math.abs(r.impactPct), 1)}%`}
      {r.confidence ? ` · độ tin cậy ${r.confidence}` : ""}
    </li>
  );
  return (
    <div className="sd-measure" data-testid="sd-measure">
      <h3 className="sa-h3">Đo lường</h3>
      <p data-testid="sd-countdown">{cd.text}</p>
      {plan.planned_days === null ? <p className="sa-hint">Lượng đơn của phạm vi này quá ít để thấy được tác động trong 28 ngày: thẻ vẫn được theo dõi, nhưng kết quả sẽ khó kết luận.</p> : null}
      {t7 || final ? <ul className="sd-readings">{[t7, final].filter((r): r is NonNullable<typeof t7> => r !== null).map(reading)}</ul> : null}
    </div>
  );
}

/**
 * "Hoàn tác" of an executed card: the steps in reverse and ONE confirmation. Juli never claims the
 * revert: the person undoes it in Seller Centre, then presses "Đã hoàn tác", which records who and
 * when, stops the card's measurement and keeps it out of what Juli learns.
 */
function RevertBlock({ detail, sheet, onChanged, revertJobs, onQueued }: { readonly detail: CardDetail; readonly sheet: ExecutionSheet; readonly onChanged: () => void; readonly revertJobs: readonly FillJobRow[]; readonly onQueued: () => void }) {
  const host = useReco();
  const sample = useSampleShopReviewer();
  const jobs = revertJobs.length > 0 ? revertJobs : (detail.revert?.jobs ?? []);
  const [open, setOpen] = useState(jobs.length > 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reverted = detail.reverted ?? null;
  const ready = detail.revert?.ready === true;
  const canFill = !sample && !!host.reco.revertFill;
  const confirm = async (manual: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await (manual ? host.reco.reverted(detail.id, { manual: true }) : host.reco.reverted(detail.id));
      onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const queueFill = async () => {
    if (!host.reco.revertFill) return;
    setBusy(true);
    setError(null);
    // the tab is opened inside the click (popup blockers), then pointed at the queued revert job
    const tab = typeof window === "undefined" ? null : window.open("", "_blank");
    if (tab) tab.opener = null;
    try {
      const queued = await host.reco.revertFill(detail.id);
      const job = (queued.jobs ?? []).find((j) => j.status === "queued" || j.status === "opened" || j.status === "filled");
      const target = job ? fillJobHref(job) : null;
      if (tab && target) tab.location.href = target;
      else tab?.close();
      setOpen(true);
      onQueued();
    } catch (e) {
      tab?.close();
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  if (reverted) {
    return (
      <div className="sd-revert" data-testid="sd-reverted">
        <TextChip tone="flat">Đã hoàn tác</TextChip> <span>lúc {vnWhen(reverted.at)}</span>
      </div>
    );
  }
  const openJob = jobs.find((j) => j.status === "queued" || j.status === "opened" || j.status === "filled");
  // K3: the revert job's own page (the card's `job` while an undo is queued), never the forward create page
  const href = (detail.job?.role === "revert" ? jobHref(detail.job) : null) ?? (openJob ? fillJobHref(openJob) : null);
  const blockedTitle = host.readOnly ? READ_ONLY_TITLE : undefined;
  return (
    <div className="sd-revert" data-testid="sd-revert">
      <div className="sd-actions">
        <button aria-expanded={open} className="sa-btn" data-testid="sd-revert-toggle" onClick={() => setOpen((v) => !v)} type="button">
          Hoàn tác
        </button>
      </div>
      {open ? (
        <>
          {canFill ? (
            <div className="sd-actions">
              {href ? (
                <a className="sa-btn sa-btn--primary" data-testid="sd-revert-open" href={href} rel="noopener noreferrer" target="_blank">
                  Mở và điền
                </a>
              ) : (
                <button className="sa-btn sa-btn--primary" data-testid="sd-revert-fill" disabled={!!host.readOnly || busy} onClick={() => void queueFill()} title={blockedTitle} type="button">
                  Mở và điền
                </button>
              )}
            </div>
          ) : null}
          <FillJobsChecklist enabled jobs={jobs} />
          <SheetView fillHref={href} reverse sheet={sheet} />
          <div className="sd-actions">
            <button className="sa-btn sa-btn--primary" data-testid="sd-reverted-confirm" disabled={!!host.readOnly || busy || (canFill && !ready)} onClick={() => void confirm(false)} title={blockedTitle} type="button">
              Đã hoàn tác
            </button>
            {canFill ? (
              <button className="sa-btn" data-testid="sd-reverted-manual" disabled={!!host.readOnly || busy} onClick={() => void confirm(true)} title={blockedTitle} type="button">
                Đã hoàn tác thủ công
              </button>
            ) : null}
          </div>
        </>
      ) : null}
      {error ? (
        <p className="sd-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function ExecutionPanel({ detail, sheet, onExecuted, onReverted, onRefresh }: { readonly detail: CardDetail; readonly sheet: ExecutionSheet; readonly onExecuted: () => void; readonly onReverted?: () => void; readonly onRefresh?: () => void }) {
  const host = useReco();
  const [voucherId, setVoucherId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rb = readbackOf(detail.journey);
  const executed = detail.status === "executed";
  const reverted = !!detail.reverted;
  // P97 D85.6: after the person saves, the Connector captures the new voucher id itself.
  // P100 S2-D4: no Connector (so no fill queue, which the sample pin refuses) on the reviewer's sample shop.
  const sample = useSampleShopReviewer();
  // P100 S2-F2: the sample shop has no Seller Centre voucher to copy a code from; the server
  // gives the sample voucher its own code, so the field is not asked for there.
  const needsVoucherId = !sample && sheet.changes.some((c) => c.change_kind === "voucher");
  const fillActive = !sample && detail.status === "approved" && FILL_JOB_KINDS.has(detail.change_kind);
  // F3: an executed card also lists its revert and read-back jobs (the server sends them whatever the card's status)
  const fill = useFillJobs(detail.id, fillActive || (!sample && executed));
  const forwardJobs = fill.jobs.filter(isForwardJob);
  const revertJobs = fill.jobs.filter(isRevertJob);
  const captured = capturedVoucherId(fill.jobs);
  // F3.2: when a read-back / revert job moves, the card is re-read so Khớp / Không khớp and "ready" show without a reload
  const sig = executed ? fill.jobs.map((j) => `${j.id}:${j.status}`).join("|") : "";
  const prevSig = useRef("");
  useEffect(() => {
    if (prevSig.current !== "" && sig !== prevSig.current) onRefresh?.();
    prevSig.current = sig;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);
  // K4: Đã làm is offered for every kind with a forward job; the code / id box is optional
  const hasForward = !sample && (forwardJobs.length > 0 || detail.job?.role === "forward");
  const showBox = needsVoucherId || hasForward;
  const blocked = !!host.readOnly || busy || detail.can_mark_done === false || (needsVoucherId && voucherId.trim() === "" && !captured && !detail.job);
  // ONE page button: "Mở và điền" opens the card's current job (K3), else the page itself
  const openJob = fill.enabled && !executed ? forwardJobs.find((j) => j.status === "queued" || j.status === "opened" || j.status === "filled") : undefined;
  const fillHref = (detail.job?.role === "forward" ? jobHref(detail.job) : null) ?? (openJob ? fillJobHref(openJob) : null);

  const markDone = async () => {
    setBusy(true);
    setError(null);
    try {
      await host.reco.executed(detail.id, showBox ? markDoneBody(voucherId || captured || "") : {});
      onExecuted();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="sa-card sd-exec" data-testid="sd-execution">
      <div className="sa-card__head">
        <h2 className="sa-h2">{executed ? "Đã làm trên Seller Centre" : "Làm trên Seller Centre"}</h2>
      </div>
      {executed ? (
        <>
          {reverted ? null : <ReadbackBlock deadline={sheet.readback.deadline_hours} rb={rb} />}
          {reverted ? null : <Measurement detail={detail} rb={rb} />}
          <details className="sd-exec__sheet">
            <summary>Xem lại bảng thao tác</summary>
            <SheetView sheet={sheet} />
          </details>
          <RevertBlock detail={detail} onChanged={onReverted ?? onExecuted} onQueued={fill.reload} revertJobs={revertJobs} sheet={sheet} />
        </>
      ) : (
        <>
          <SheetView fillHref={fillHref} sheet={sheet} />
          <ListingSheetExtras detail={detail} sheet={sheet} />
          <FillJobsChecklist enabled={fill.enabled} jobs={forwardJobs} />
          {detail.job ? <JobLine job={detail.job} /> : null}
          {needsVoucherId && captured ? (
            <p className="sa-hint" data-testid="sd-voucher-captured">
              Connector đã lấy mã voucher {captured}.
            </p>
          ) : showBox ? (
            <label className="sd-voucher-id">
              {needsVoucherId ? "Mã voucher trên Seller Centre" : "Mã hoặc ID trên Seller Centre"}
              <input
                disabled={!!host.readOnly}
                onChange={(event) => setVoucherId(event.target.value)}
                placeholder="Ví dụ: 1234567890"
                type="text"
                value={voucherId}
              />
            </label>
          ) : null}
          <div className="sd-actions">
            <button className="sa-btn sa-btn--primary" disabled={blocked} onClick={() => void markDone()} title={host.readOnly ? READ_ONLY_TITLE : undefined} type="button">
              Đã làm
            </button>
          </div>
        </>
      )}
      {error ? (
        <p className="sd-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
