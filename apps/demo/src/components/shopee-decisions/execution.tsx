"use client";

import { useState } from "react";

import { DASH, fmt } from "../../lib/shopee-analytics/format";
import { useReco } from "../../lib/shopee-decisions/context";
import { READBACK_LABEL, countdownOf, readbackOf, readingsOf, stepText, vnWhen, type Readback } from "../../lib/shopee-decisions/model";
import type { CardDetail, ExecutionSheet, ExecutionStep, SheetPage } from "../../lib/shopee-decisions/types";
import { TextChip } from "../shopee-analytics/ui";
import { CopyButton, errorText } from "./ui";

/**
 * Assisted execution (p90-plan "Assisted execution"): Juli never writes to Seller Centre. An
 * approved card shows the sheet - the page, each field with its exact before -> after (with copy
 * buttons) and the time window - and a link to open the page. A person saves it with Shopee's own
 * button, then marks "Đã làm"; the Connector's next readings say Chờ xác minh / Đã xác minh /
 * Không khớp / Chưa thấy, and the 14 / 28-day measurement starts when the change is verified.
 * "Hoàn tác" shows the same steps in reverse.
 */

export const READ_ONLY_TITLE = "Chế độ xem: không thể thao tác thay seller";

export function PageLink({ page }: { readonly page: SheetPage }) {
  return (
    <span className="sd-page" data-testid="sd-page">
      <b>{page.label}</b>
      {page.deep_link ? (
        <a className="sa-btn sa-btn--primary sa-btn--s" href={page.deep_link} rel="noopener noreferrer" target="_blank">
          {page.button || "Mở trang để sửa"}
        </a>
      ) : (
        <span className="sa-hint">Chưa có đường dẫn trực tiếp: vào menu &ldquo;{page.label}&rdquo; trong Seller Centre.</span>
      )}
      {page.verified ? null : <TextChip tone="warn">đường dẫn chưa kiểm</TextChip>}
    </span>
  );
}

function StepRow({ step }: { readonly step: ExecutionStep }) {
  return (
    <li className="sd-step" data-testid={`sd-step-${step.order}`}>
      <span className="sd-step__n">{step.order}</span>
      <span className="sd-step__field">
        <b>{step.field}</b>
        {step.page ? <PageLink page={step.page} /> : null}
        {step.starts ? <span className="sa-hint">Bật lúc {vnWhen(step.starts)}</span> : null}
      </span>
      <span className="sd-step__before">{stepText(step.before, step.unit)}</span>
      <span aria-hidden="true">→</span>
      <b className="sd-step__after">{stepText(step.after, step.unit)}</b>
      {step.copy ? <CopyButton label={step.field} text={step.copy} /> : <span />}
    </li>
  );
}

export function SheetView({ sheet, reverse = false }: { readonly sheet: ExecutionSheet; readonly reverse?: boolean }) {
  const steps = reverse ? sheet.revert_steps : sheet.steps;
  const w = sheet.time_window;
  return (
    <div className="sd-sheet" data-testid={reverse ? "sd-revert-sheet" : "sd-sheet"}>
      <PageLink page={sheet.page} />
      <ol className="sd-steps">
        {steps.map((s) => (
          <StepRow key={s.order} step={s} />
        ))}
      </ol>
      <p className="sa-hint" data-testid="sd-time-window">
        Thời gian: {w.start ?? DASH}
        {typeof w.days === "number" ? ` · chạy ${fmt(w.days, 0)} ngày` : ""}
      </p>
      <p className="sa-hint">{sheet.save_hint}</p>
    </div>
  );
}

const READBACK_TONE = { pending: "warn", verified: "up", mismatch: "down", not_seen: "warn", none: "flat" } as const;

function ReadbackBlock({ rb, deadline }: { readonly rb: Readback; readonly deadline: number }) {
  if (rb.state === "none") return null;
  return (
    <div className={`sd-readback sd-readback--${rb.state}`} data-testid="sd-readback">
      <TextChip tone={READBACK_TONE[rb.state]}>{READBACK_LABEL[rb.state]}</TextChip>
      <span>
        {rb.state === "pending" ? `Juli đọc lại ở lần chạy kế tiếp của Connector; chưa thấy sau ${deadline} giờ sẽ báo cho Ops.` : null}
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

export function ExecutionPanel({ detail, sheet, onExecuted }: { readonly detail: CardDetail; readonly sheet: ExecutionSheet; readonly onExecuted: () => void }) {
  const host = useReco();
  const [revert, setRevert] = useState(false);
  const [voucherId, setVoucherId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rb = readbackOf(detail.journey);
  const executed = detail.status === "executed";
  const needsVoucherId = sheet.changes.some((c) => c.change_kind === "voucher");
  const blocked = !!host.readOnly || busy || (needsVoucherId && voucherId.trim() === "");

  const markDone = async () => {
    setBusy(true);
    setError(null);
    try {
      await host.reco.executed(detail.id, { voucherId: needsVoucherId ? voucherId.trim() : null });
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
        <span className="sa-hint">Juli không bấm lưu thay bạn: bạn sửa theo bảng dưới, bấm Lưu của chính Shopee, rồi báo &ldquo;Đã làm&rdquo;.</span>
      </div>
      {executed ? (
        <>
          <ReadbackBlock deadline={sheet.readback.deadline_hours} rb={rb} />
          <Measurement detail={detail} rb={rb} />
          <details className="sd-exec__sheet">
            <summary>Xem lại bảng thao tác</summary>
            <SheetView sheet={sheet} />
          </details>
        </>
      ) : (
        <>
          <SheetView sheet={sheet} />
          {needsVoucherId ? (
            <label className="sd-voucher-id">
              Mã voucher trên Seller Centre (sau khi tạo)
              <input
                disabled={!!host.readOnly}
                onChange={(event) => setVoucherId(event.target.value)}
                placeholder="Ví dụ: 1234567890"
                type="text"
                value={voucherId}
              />
              <span className="sa-hint">Cần mã này để Juli đọc lại voucher và xác minh.</span>
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
      <div className="sd-actions">
        <button aria-expanded={revert} className="sa-btn" onClick={() => setRevert((v) => !v)} type="button">
          Hoàn tác
        </button>
        <span className="sa-hint">Hoàn tác là sửa lại trên Seller Centre theo các bước ngược, rồi báo cho đội Juli để ghi lại.</span>
      </div>
      {revert ? <SheetView reverse sheet={sheet} /> : null}
    </section>
  );
}
