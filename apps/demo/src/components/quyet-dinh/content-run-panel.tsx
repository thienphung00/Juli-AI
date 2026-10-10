"use client";

import { useEffect, useState } from "react";

import type { CardView } from "../../lib/quyet-dinh/card-model";
import type { ContentRunDetail, ContentScript, ContentStage, QdRun } from "../../lib/quyet-dinh/p10-types";
import { DECLINE_REASONS, reasonOption, type ReasonChoice } from "../../lib/quyet-dinh/reasons";
import type { Chip } from "../../lib/quyet-dinh/run-model";
import { vnTime, type RunTimeline } from "../../lib/quyet-dinh/timeline";
import { RUN_TERMINAL_STATE_COPY, RUN_TERMINAL_STATE_UNKNOWN_COPY } from "../../lib/run-ledger/copy";
import { resolveRunTerminalState } from "../../lib/run-ledger/terminal-state";
import { ReasonDialog, ReasonDone, SKIP_DIALOG_BODY } from "./reason-dialog";

/**
 * One "Juli soạn · bạn làm" run in Đang thực hiện (P14-E, `ContentRun.dc.html`,
 * contract `p14-content-cards.md` §2): the six steps, the drafted script
 * (bản 1 / 2, editable in place) with Dùng kịch bản này / Soạn lại / Sao chép /
 * Không thực hiện, the wait for the seller's video or LIVE, then the
 * measuring note. Juli writes nothing to TikTok, so there is no Hoàn tác.
 * The run detail's `content` block is the source; the SSE timeline only
 * supplies the narration while drafting and the terminal event.
 */

export type ContentPhase = ContentStage;

const DRAFTS_CHIP = "Juli soạn · bạn làm";
/** Steps the seller does (ContentRun.dc.html: "Đang chờ bạn" while current). */
const SELLER_STEPS = new Set([3, 4]);
/** Where the current step sits for each stage (the artboard's `pos`). */
const STAGE_POS: Readonly<Record<ContentStage, number>> = {
  drafting: 0,
  choice: 3,
  publish: 4,
  measuring: 5,
  declined: 3,
  ended: 3,
};

/** The run's phase: the terminal event wins over the (polled) detail. */
export function contentPhase(run: QdRun, detail: ContentRunDetail | null, timeline: RunTimeline, declined: boolean): ContentPhase {
  const terminal = timeline.terminal;
  if (terminal) {
    if (terminal.stopReason === "cancelled_by_seller" || terminal.stopReason === "confirmation_declined") return "declined";
    if (terminal.kind === "completed" && terminal.stopReason === "final_response") return "measuring";
    return "ended";
  }
  if (declined) return "declined";
  if (run.stop_reason === "cancelled_by_seller") return "declined";
  if (run.status === "completed" && run.stop_reason === "final_response") return "measuring";
  if (run.awaiting === "content_publish") return "publish";
  if (run.awaiting === "content_choice") return detail?.script ? "choice" : (detail?.stage ?? "drafting");
  return detail?.stage ?? "drafting";
}

export function contentChip(phase: ContentPhase, stopReason: string | null): Chip {
  switch (phase) {
    case "drafting":
      return { label: "Đang chạy", tone: "info" };
    case "choice":
    case "publish":
      return { label: "Đang chờ bạn", tone: "wait" };
    case "measuring":
      return { label: "Đang đo", tone: "info" };
    case "declined":
      return { label: "Không thay đổi", tone: "muted" };
    case "ended": {
      const key = resolveRunTerminalState(stopReason);
      return { label: (key ? RUN_TERMINAL_STATE_COPY[key] : RUN_TERMINAL_STATE_UNKNOWN_COPY).label, tone: "muted" };
    }
  }
}

export interface ContentStepView {
  readonly key: string;
  readonly label: string;
  readonly result: string | null;
  readonly time: string | null;
  readonly state: "done" | "current" | "todo";
}

/** ContentRun.dc.html's step rows: done before `pos`, current at `pos`, grey after. */
export function contentSteps(detail: ContentRunDetail, phase: ContentPhase): ContentStepView[] {
  let pos = STAGE_POS[phase];
  if (phase === "drafting") {
    const first = detail.steps.findIndex((step) => !step.at);
    pos = first === -1 ? 3 : Math.min(first, 3);
  }
  const noCurrent = phase === "declined" || phase === "ended";
  return detail.steps.map((step, index) => {
    const done = index < pos;
    const current = index === pos && !noCurrent;
    const fallback = current ? (SELLER_STEPS.has(index) ? "Đang chờ bạn" : index === 5 ? "Đang đo" : null) : null;
    return {
      key: step.key,
      label: step.label,
      result: done || current ? (step.result ?? fallback) : null,
      time: done && step.at ? vnTime(step.at) : null,
      state: done ? "done" : current ? "current" : "todo",
    };
  });
}

/** Sao chép: the backend's plain text, or the blocks as the seller edited them. */
export function copyText(script: ContentScript, edited: Readonly<Record<string, string>>): string {
  if (Object.keys(edited).length === 0 && script.plain_text) return script.plain_text;
  return [script.title, ...script.blocks.map((block) => `${block.label}\n${edited[block.key] ?? block.text}`)].join("\n\n");
}

export interface ContentRunPanelProps {
  readonly run: QdRun;
  readonly card: CardView | null;
  readonly detail: ContentRunDetail | null;
  readonly timeline: RunTimeline;
  readonly phase: ContentPhase;
  readonly chip: Chip;
  readonly reconnecting: boolean;
  readonly measureHref: string;
  readonly onOpenMeasure: (event: React.MouseEvent<HTMLAnchorElement>) => void;
  readonly onUse: (version: number, editedBlocks: Readonly<Record<string, string>> | null) => Promise<void>;
  readonly onRedraft: () => Promise<void>;
  readonly onPublished: () => Promise<void>;
  readonly onDecline: (choice: ReasonChoice) => Promise<void>;
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function ContentRunPanel(props: ContentRunPanelProps) {
  const { run, card, detail, timeline, phase, chip } = props;
  const [dialog, setDialog] = useState(false);
  const [dialogBusy, setDialogBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [declinedReason, setDeclinedReason] = useState<string | null>(null);
  const headingId = `run-${run.id}`;
  const sku = card?.sku ? `${card.sku} · ` : "";
  const title = detail?.title ?? `${sku}${card?.title ?? run.product_name}`;
  const steps = detail ? contentSteps(detail, phase) : [];

  return (
    <section aria-labelledby={headingId} className="qv-run qv-content-run" data-kind="content" data-phase={phase} data-testid="run-detail">
      <div className="qv-run__head">
        <span className={`qv-chip qv-tone--${chip.tone}`} data-testid="run-chip">
          {chip.label}
        </span>
        <h2 className="qv-run__title" id={headingId}>
          {title}
        </h2>
        <span className="qv-drafts-chip qv-drafts-chip--head">{DRAFTS_CHIP}</span>
      </div>

      {props.reconnecting ? (
        <p className="qv-status-line" role="status">
          Đang kết nối lại…
        </p>
      ) : null}

      {detail ? (
        <ol aria-label="Các bước" className="qv-steps qv-steps--wide" data-testid="content-steps">
          {steps.map((step, index) => (
            <li className={`qv-step${step.state === "todo" ? "" : ` qv-step--${step.state}`}`} data-state={step.state} key={step.key}>
              <span aria-hidden="true" className="qv-step__dot">
                {step.state === "done" ? "✓" : String(index + 1)}
              </span>
              <div className="qv-step__body">
                <span className="qv-step__label">{step.label}</span>
                <span className="qv-step__result">{step.result ?? ""}</span>
              </div>
              <span className="qv-step__time">{step.time ?? ""}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="qv-status-line" role="status">
          Đang tải các bước của lượt chạy…
        </p>
      )}

      {phase === "drafting" ? (
        <div className="qv-running" role="status">
          <span>{timeline.narration ?? "Juli đang đọc số liệu và soạn kịch bản…"}</span>
        </div>
      ) : null}

      {phase === "choice" && detail?.script ? (
        <ScriptBox
          canRedraft={detail.can_redraft}
          key={detail.script.version}
          onRedraft={props.onRedraft}
          onSkip={() => {
            setDialogError(null);
            setDialog(true);
          }}
          onUse={props.onUse}
          script={detail.script}
        />
      ) : null}

      {phase === "publish" && detail?.wait ? <WaitBox onPublished={props.onPublished} wait={detail.wait} /> : null}

      {phase === "measuring" ? (
        <div className="qv-measure-box" data-testid="content-measuring">
          <div className="qv-measure-box__title">Đang đo kết quả</div>
          {detail?.measure_body ? <div className="qv-measure-box__body">{detail.measure_body}</div> : null}
          <a className="qv-measure-box__link" href={props.measureHref} onClick={props.onOpenMeasure}>
            Xem ở Đo lường ›
          </a>
        </div>
      ) : null}

      {phase === "declined" ? (
        declinedReason ? (
          <ReasonDone
            lines={[
              "Không có gì được ghi lên TikTok Shop.",
              "Thẻ không quay lại Đề xuất ngay. Juli có thể đề xuất lại kịch bản cho sản phẩm này sau 7 ngày.",
            ]}
            reason={reasonOption(DECLINE_REASONS, declinedReason)}
            title="Hoàn thành · không thực hiện thay đổi"
          />
        ) : (
          <div className="qv-grey">Bạn chọn không dùng kịch bản. Lượt chạy kết thúc, không có gì được đo.</div>
        )
      ) : null}

      {phase === "ended" && timeline.terminal ? (
        <div className="qv-grey">
          {(() => {
            const key = resolveRunTerminalState(timeline.terminal.stopReason);
            return (key ? RUN_TERMINAL_STATE_COPY[key] : RUN_TERMINAL_STATE_UNKNOWN_COPY).body;
          })()}
        </div>
      ) : null}

      <ReasonDialog
        body={SKIP_DIALOG_BODY}
        busy={dialogBusy}
        error={dialogError}
        mode="skip"
        onCancel={() => setDialog(false)}
        onSubmit={(choice) => {
          setDialogBusy(true);
          setDialogError(null);
          props
            .onDecline(choice)
            .then(() => {
              setDeclinedReason(choice.reason_code);
              setDialog(false);
            })
            .catch((error: unknown) => setDialogError(errorText(error, "Chưa gửi được lựa chọn. Vui lòng thử lại.")))
            .finally(() => setDialogBusy(false));
        }}
        open={dialog}
      />
    </section>
  );
}

function ScriptBox({
  script,
  canRedraft,
  onUse,
  onRedraft,
  onSkip,
}: {
  readonly script: ContentScript;
  readonly canRedraft: boolean;
  readonly onUse: ContentRunPanelProps["onUse"];
  readonly onRedraft: ContentRunPanelProps["onRedraft"];
  readonly onSkip: () => void;
}) {
  const [edited, setEdited] = useState<Readonly<Record<string, string>>>({});
  const [busy, setBusy] = useState<"use" | "redraft" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const run = (which: "use" | "redraft", action: () => Promise<void>) => {
    if (busy) return;
    setBusy(which);
    setError(null);
    action()
      .catch((reason: unknown) => setError(errorText(reason, "Chưa gửi được. Vui lòng thử lại.")))
      .finally(() => setBusy(null));
  };

  return (
    <div className="qv-script" data-testid="content-script">
      <div className="qv-script__head">
        <span className="qv-script__title">{script.title}</span>
        <span className="qv-script__version">Bản {script.version} · bạn sửa trực tiếp được</span>
      </div>
      <div className="qv-script__blocks">
        {script.blocks.map((block) => {
          const value = edited[block.key] ?? block.text;
          return (
            <div className="qv-script__block" key={block.key}>
              <span className="qv-script__k">{block.label}</span>
              <textarea
                aria-label={block.label}
                className="qv-script__v"
                onChange={(event) => {
                  const next = event.target.value;
                  setEdited((map) => {
                    const copy = { ...map };
                    if (next === block.text) delete copy[block.key];
                    else copy[block.key] = next;
                    return copy;
                  });
                }}
                rows={Math.max(1, value.split("\n").length)}
                value={value}
              />
            </div>
          );
        })}
      </div>
      <div className="qv-script__checks">{script.checks_line}</div>
      {error ? (
        <p className="qv-inline-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="qv-script__actions">
        <button
          className="qv-btn qv-btn--primary"
          disabled={busy !== null}
          onClick={() => run("use", () => onUse(script.version, Object.keys(edited).length > 0 ? edited : null))}
          type="button"
        >
          {busy === "use" ? "Đang gửi…" : "Dùng kịch bản này"}
        </button>
        <button
          className="qv-btn qv-btn--secondary"
          disabled={!canRedraft || busy !== null}
          onClick={() => run("redraft", onRedraft)}
          title={canRedraft ? undefined : "Juli đã soạn lại một lần."}
          type="button"
        >
          {busy === "redraft" ? "Juli đang soạn lại…" : "Soạn lại"}
        </button>
        <button
          className="qv-btn qv-btn--ghost qv-script__copy"
          onClick={() => {
            const text = copyText(script, edited);
            void navigator.clipboard
              ?.writeText(text)
              .then(() => setCopied(true))
              .catch(() => setError("Chưa sao chép được. Bạn chọn và sao chép thủ công."));
          }}
          type="button"
        >
          {copied ? "Đã sao chép" : "Sao chép"}
        </button>
        <button className="qv-btn qv-btn--secondary qv-script__skip" disabled={busy !== null} onClick={onSkip} type="button">
          Không thực hiện
        </button>
      </div>
    </div>
  );
}

function WaitBox({
  wait,
  onPublished,
}: {
  readonly wait: NonNullable<ContentRunDetail["wait"]>;
  readonly onPublished: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="qv-wait-box" data-testid="content-wait">
      <div className="qv-wait-box__title">{wait.title}</div>
      <div className="qv-wait-box__body">{wait.body}</div>
      {error ? (
        <p className="qv-inline-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="qv-wait-box__actions">
        <button
          className="qv-btn qv-btn--primary"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setError(null);
            onPublished()
              .catch((reason: unknown) => setError(errorText(reason, "Chưa gửi được. Vui lòng thử lại.")))
              .finally(() => setBusy(false));
          }}
          type="button"
        >
          {wait.done_label}
        </button>
        <span className="qv-wait-box__hint">Hoặc để Juli tự nhận ra khi có {wait.detect_what}.</span>
      </div>
    </div>
  );
}
