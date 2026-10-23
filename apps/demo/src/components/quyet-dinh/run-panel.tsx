"use client";

import { useRef, useState } from "react";

import type { CardView } from "../../lib/quyet-dinh/card-model";
import { consentRows, editableFields, photoUrls, proposedText } from "../../lib/quyet-dinh/consent-model";
import { dateText, validityText } from "../../lib/quyet-dinh/p10-format";
import type { PhotoCheck, QdRun, SellerInstructions } from "../../lib/quyet-dinh/p10-types";
import type { ReasonChoice } from "../../lib/quyet-dinh/reasons";
import { runChip, runningNote, type RunPhase } from "../../lib/quyet-dinh/run-model";
import { useSandboxReviewer } from "../../lib/reviewer/mode";
import { SIMULATED_DONE_TEXT, SIMULATED_DONE_TITLE } from "../../lib/quyet-dinh/simulated-copy";
import type { RunKind, RunTimeline } from "../../lib/quyet-dinh/timeline";
import type { RunChanges } from "../../lib/quyet-dinh/types";
import { RUN_TERMINAL_STATE_COPY, RUN_TERMINAL_STATE_UNKNOWN_COPY } from "../../lib/run-ledger/copy";
import { resolveRunTerminalState } from "../../lib/run-ledger/terminal-state";
import { ConfirmationRejectedError, type EditedValues } from "../../lib/run-surface/confirmation-decision";
import { DECLINE_REASONS, REVERT_REASONS, reasonOption } from "../../lib/quyet-dinh/reasons";
import { ReasonDialog, ReasonDone, SKIP_DIALOG_BODY, revertDialogBody } from "./reason-dialog";
import { Chevron, StageChips, StepList, timelineRows } from "./run-steps";
import { useRunActions, useRunControl, useSellerHref, useWriteControl } from "../seller-view-context";

/**
 * One run in Đang thực hiện (ADR-109 Amendment 1 d.3–5, d.7):
 * `Run.dc.html` (title / description: consent with "✎ Sửa nội dung trước
 * khi áp dụng"), `RunPhoto.dc.html` (cover image: photo request → checks →
 * consent with both images), `RunManual.dc.html` (promotions: checklist →
 * "Tôi đã áp dụng" → Juli verifies; no Hoàn tác) and `Revert.dc.html` (a
 * revert run). The timeline is the SSE fold (`buildRunTimeline`); every
 * write goes through the caller's handlers.
 */

const MAX_PHOTO_BYTES = 5 * 1024 * 1024;
const PHOTO_TYPES = new Set(["image/jpeg", "image/png"]);

export type PhotoState =
  | { readonly status: "idle" }
  | { readonly status: "uploading" }
  | { readonly status: "error"; readonly message: string };

export type LoadState<T> = { readonly status: "loading" } | { readonly status: "error" } | { readonly status: "ready"; readonly data: T };

export interface RunPanelProps {
  readonly run: QdRun;
  readonly kind: RunKind;
  readonly phase: RunPhase;
  readonly timeline: RunTimeline;
  readonly card: CardView | null;
  readonly changes: RunChanges | null;
  readonly nowMs: number | null;
  readonly reconnecting: boolean;
  readonly eventsLoaded: boolean;
  readonly photoChecks: readonly PhotoCheck[] | null;
  readonly photoState: PhotoState;
  /** The cover-photo run's stored before/after (`GET /v1/demo/runs/{id}` → `photo`). */
  readonly photoUrls?: { readonly before: string | null; readonly after: string | null } | null;
  readonly instructions: LoadState<SellerInstructions> | null;
  readonly appliedState: { readonly busy: boolean; readonly error: string | null };
  readonly revertReasonLabel?: string | null;
  readonly revertConflict: string | null;
  readonly revertError: string | null;
  readonly revertBusy: boolean;
  readonly measureHref: string;
  readonly onOpenMeasure: (event: React.MouseEvent<HTMLAnchorElement>) => void;
  readonly onConfirm: (toolCallId: string, optionId: string, edited: EditedValues | null) => Promise<void>;
  readonly onDecline: (choice: ReasonChoice) => Promise<void>;
  readonly onCancelRevert: () => Promise<void>;
  readonly onUpload: (file: File) => Promise<void>;
  readonly onApplied: () => Promise<void>;
  readonly onRevert: (choice: ReasonChoice) => void;
}

function titleOf(kind: RunKind, run: QdRun, card: CardView | null): string {
  const sku = card?.sku ? `${card.sku} · ` : "";
  const name = card?.title ?? run.product_name;
  if (kind === "revert") return `Hoàn tác · ${sku}${name}`;
  if (kind === "create") return `Tạo sản phẩm · từ ${name}`;
  if (kind === "promotion") return `Tạo khuyến mãi · ${run.product_name}`;
  if (kind === "manual") return `${sku}${name}${card?.leverLabel ? ` · ${card.leverLabel}` : ""}`;
  return `Lượt chạy · ${sku}${name}`;
}

function fieldList(labels: readonly string[]): string {
  return labels.join(", ");
}

export function RunPanel(props: RunPanelProps) {
  const { run, kind, phase, timeline, card, changes, reconnecting, eventsLoaded } = props;
  const [expanded, setExpanded] = useState(true);
  const [dialog, setDialog] = useState<"skip" | "revert" | null>(null);
  /** The reason code the seller gave for Không thực hiện in this visit (the completion message). */
  const [declinedReason, setDeclinedReason] = useState<string | null>(null);
  const [dialogBusy, setDialogBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const sandboxShop = useSandboxReviewer();
  const chip = runChip(run, kind, phase, sandboxShop);
  const headingId = `run-${run.id}`;
  const changedLabels =
    changes && changes.changes.length > 0
      ? changes.changes.map((change) => change.label)
      : (card?.changeLabels ?? []);
  const note = runningNote(kind, phase, timeline.narration);
  const streamingNote = timeline.narrationStreaming && note !== null && note === timeline.narration;
  const day7 = timeline.terminal?.day7 ?? null;
  const day14 = timeline.terminal?.day14 ?? null;

  const openSkip = () => {
    setDialogError(null);
    setDialog("skip");
  };

  return (
    <section aria-labelledby={headingId} className="qv-run" data-kind={kind} data-phase={phase} data-testid="run-detail">
      <div className="qv-run__head">
        <span className={`qv-chip qv-tone--${chip.tone}`} data-testid="run-chip">
          {chip.label}
        </span>
        <h2 className="qv-run__title" id={headingId}>
          {titleOf(kind, run, card)}
        </h2>
        <button
          aria-controls={`${headingId}-body`}
          aria-expanded={expanded}
          className="qv-toggle"
          onClick={() => setExpanded((value) => !value)}
          type="button"
        >
          {expanded ? "Thu gọn" : "Mở rộng"}
          {kind === "listing" ? <Chevron up={expanded} /> : null}
        </button>
      </div>

      {expanded ? (
        <div className="qv-run__body" id={`${headingId}-body`}>
          {kind !== "revert" ? <StageChips label={`Tiến trình · ${run.product_name}`} phase={phase} /> : null}
          {reconnecting ? (
            <p className="qv-status-line" role="status">
              Đang kết nối lại…
            </p>
          ) : null}
          {!eventsLoaded ? (
            <p className="qv-status-line" role="status">
              Đang tải các bước của lượt chạy…
            </p>
          ) : (
            <StepList rows={timelineRows(timeline.steps)} wide={kind === "manual"} />
          )}

          {phase === "photo" ? (
            <PhotoRequest checks={props.photoChecks} onUpload={props.onUpload} state={props.photoState} />
          ) : null}

          {phase === "guide" ? (
            <SellerGuide
              applied={props.appliedState}
              instructions={props.instructions}
              narration={timeline.narration}
              onApplied={props.onApplied}
              onSkip={openSkip}
            />
          ) : null}

          {phase === "consent" && timeline.pendingConsent ? (
            <ConsentBlock
              card={card}
              consent={timeline.pendingConsent}
              kind={kind}
              nowMs={props.nowMs}
              onCancelRevert={props.onCancelRevert}
              onConfirm={props.onConfirm}
              onSkip={openSkip}
              photoUrls={props.photoUrls ?? null}
              productName={run.product_name}
            />
          ) : null}

          {note && phase !== "verify" ? (
            // D71.3: while the model's text streams in, the note is a live preview
            // with a typing caret; aria-busy keeps screen readers from announcing
            // every chunk -- the committed line is announced once it lands.
            <div aria-busy={streamingNote} className="qv-running" role="status">
              <span>
                {note}
                {streamingNote ? <span aria-hidden="true" className="qv-caret" data-testid="typing-caret" /> : null}
              </span>
            </div>
          ) : null}

          {phase === "verify" ? (
            <>
              <div className="qv-running" role="status">
                <span>{note}</span>
              </div>
              <div className="qv-note">
                Nếu chưa thấy khuyến mãi: Juli báo &quot;Chưa tìm thấy trên TikTok&quot;, giữ bước 4 mở và nhắc bạn kiểm tra lại. Juli
                chỉ bắt đầu đếm ngày khi đã tìm thấy.
              </div>
            </>
          ) : null}

          {phase === "done" ? (
            <DonePanel
              card={card}
              changedLabels={changedLabels}
              changes={changes}
              day14={day14}
              day7={day7}
              kind={kind}
              measureHref={props.measureHref}
              onOpenMeasure={props.onOpenMeasure}
              onRevert={() => {
                setDialogError(null);
                setDialog("revert");
              }}
              revertBusy={props.revertBusy}
              revertReasonLabel={props.revertReasonLabel ?? null}
              simulated={run.simulated === true}
              writeSummary={timeline.steps.find((step) => step.key === "write")?.detail ?? null}
            />
          ) : null}

          {props.revertConflict ? <ConflictBox message={props.revertConflict} /> : null}
          {props.revertError ? (
            <p className="qv-inline-error" role="alert">
              {props.revertError}
            </p>
          ) : null}

          {phase === "declined" ? (
            declinedReason ? (
              <ReasonDone
                lines={[
                  "Không có gì được ghi lên TikTok Shop. Lần sau chỉ muốn sửa vài chữ, chọn Sửa nội dung ở bước xác nhận.",
                  kind === "listing"
                    ? "Thẻ không quay lại Đề xuất ngay. Juli có thể đề xuất lại sản phẩm này sau, với nội dung mới."
                    : declinedText(kind),
                ]}
                reason={reasonOption(DECLINE_REASONS, declinedReason)}
                title="Hoàn thành · không thực hiện thay đổi"
              />
            ) : (
              <div className="qv-grey">{declinedText(kind)}</div>
            )
          ) : null}
          {phase === "conflict" ? <ConflictBox message={null} /> : null}
          {phase === "ended" && timeline.terminal ? <div className="qv-grey">{endedText(timeline.terminal.stopReason)}</div> : null}
        </div>
      ) : null}

      <ReasonDialog
        body={dialog === "revert" ? revertDialogBody(changedLabels, card?.title ?? run.product_name) : SKIP_DIALOG_BODY}
        busy={dialogBusy}
        error={dialogError}
        mode={dialog ?? "skip"}
        onCancel={() => setDialog(null)}
        onSubmit={(choice) => {
          if (dialog === "revert") {
            setDialog(null);
            props.onRevert(choice);
            return;
          }
          setDialogBusy(true);
          setDialogError(null);
          props
            .onDecline(choice)
            .then(() => {
              setDeclinedReason(choice.reason_code);
              setDialog(null);
            })
            .catch((error: unknown) =>
              setDialogError(error instanceof Error && error.message ? error.message : "Chưa gửi được lựa chọn. Vui lòng thử lại."),
            )
            .finally(() => setDialogBusy(false));
        }}
        open={dialog !== null}
      />
    </section>
  );
}

function declinedText(kind: RunKind): string {
  if (kind === "photo") return "Bạn đã chọn không thay ảnh. Lượt chạy kết thúc, ảnh bìa giữ nguyên.";
  if (kind === "manual") return "Bạn chọn không áp dụng. Thẻ kết thúc, không có gì được đo.";
  if (kind === "revert") return "Bạn giữ thay đổi. Juli tiếp tục đo như cũ.";
  if (kind === "create") return "Bạn đã chọn không tạo sản phẩm. Lượt chạy kết thúc, TikTok không có gì thay đổi.";
  if (kind === "promotion") return "Bạn đã chọn không tạo khuyến mãi. Lượt chạy kết thúc, TikTok không có gì thay đổi.";
  return "Bạn đã chọn không thay đổi. Lượt chạy kết thúc, sản phẩm giữ nguyên.";
}

function endedText(stopReason: string): string {
  const key = resolveRunTerminalState(stopReason);
  return (key ? RUN_TERMINAL_STATE_COPY[key] : RUN_TERMINAL_STATE_UNKNOWN_COPY).body;
}

export function ConflictBox({ message }: { readonly message: string | null }) {
  return (
    <div className="qv-orange" data-testid="revert-conflict" role="alert">
      <div className="qv-orange__title">Juli dừng, không ghi đè</div>
      <div className="qv-orange__text">
        {message ??
          "Có người đã sửa sản phẩm ngoài Juli sau khi Juli ghi, nên Juli không tự khôi phục để tránh xoá thay đổi đó."}
      </div>
      <div className="qv-orange__text">
        Bạn có thể: giữ nguyên như hiện tại, hoặc sửa tay trên Seller Center. Kết quả đo của thay đổi này dừng lại vì sản phẩm
        đã bị sửa thêm.
      </div>
    </div>
  );
}

// -- consent (Run.dc.html / Revert.dc.html / RunPhoto.dc.html) ------------------------------

function ConsentBlock({
  consent,
  kind,
  card,
  productName,
  nowMs,
  onConfirm,
  onSkip,
  onCancelRevert,
  photoUrls: runPhotos,
}: {
  readonly consent: NonNullable<RunTimeline["pendingConsent"]>;
  readonly kind: RunKind;
  readonly card: CardView | null;
  readonly productName: string;
  readonly nowMs: number | null;
  readonly onConfirm: RunPanelProps["onConfirm"];
  readonly onSkip: () => void;
  readonly onCancelRevert: () => Promise<void>;
  readonly photoUrls: RunPanelProps["photoUrls"];
}) {
  const write = useRunControl();
  const options =
    consent.options.length > 0
      ? consent.options
      : [{ option_id: "default", proposed_change: consent.proposedChange, rationale: "", params_sha: "" }];
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [edited, setEdited] = useState<EditedValues | null>(null);
  const [draft, setDraft] = useState<{ title: string; description: string; discount: string; endDate: string }>({
    title: "",
    description: "",
    discount: "",
    endDate: "",
  });
  const [status, setStatus] = useState<"idle" | "submitting">("idle");
  const [error, setError] = useState<{ message: string; field: string | null } | null>(null);
  const isPhoto = kind === "photo" || consent.toolName === "upload_product_image";
  const isRevert = kind === "revert";
  const isPromotion = kind === "promotion";
  const validity = validityText(consent.expiresAt, nowMs);
  const expired = validity === "Đã hết hiệu lực";
  const target = options.find((option) => option.option_id === selected) ?? options[0];
  const editable = !isPhoto && !isRevert && !isPromotion ? editableFields(target.proposed_change) : [];
  const canEdit = editable.length > 0 || isPromotion;
  const proposedPct = proposedText(target.proposed_change.discount_pct) ?? "";
  const proposedEnd = proposedText(target.proposed_change.end_date) ?? "";

  const startEdit = () => {
    setDraft({
      title: edited?.title ?? proposedText(target.proposed_change.title) ?? "",
      description: edited?.description ?? proposedText(target.proposed_change.description) ?? "",
      discount: edited?.discount_pct !== undefined ? String(edited.discount_pct) : proposedPct,
      endDate: edited?.end_date ?? proposedEnd,
    });
    setEditing(true);
  };

  // "Huỷ sửa" discards the seller's version entirely: the card shows Juli's proposal
  // again and a plain confirm sends no edited_values (P64 walkthrough).
  const cancelEdit = () => {
    setEdited(null);
    setError(null);
    setEditing(false);
  };

  const savePromotionEdit = () => {
    const pct = draft.discount.trim();
    if (!/^\d{1,2}$/.test(pct)) {
      setError({ message: "Mức giảm cần là số nguyên phần trăm.", field: "discount_pct" });
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(draft.endDate)) {
      setError({ message: "Chọn ngày kết thúc.", field: "end_date" });
      return;
    }
    const next: { discount_pct?: number; end_date?: string } = {};
    if (pct !== proposedPct) next.discount_pct = Number(pct);
    if (draft.endDate !== proposedEnd) next.end_date = draft.endDate;
    setError(null);
    setEdited(Object.keys(next).length > 0 ? next : null);
    setSelected(target.option_id);
    setEditing(false);
  };

  const saveEdit = () => {
    if (isPromotion) {
      savePromotionEdit();
      return;
    }
    const next: { title?: string; description?: string } = {};
    if (editable.includes("title") && draft.title.trim() !== (proposedText(target.proposed_change.title) ?? "")) {
      next.title = draft.title.trim();
    }
    if (editable.includes("description") && draft.description.trim() !== (proposedText(target.proposed_change.description) ?? "").trim()) {
      next.description = draft.description.trim();
    }
    if (editable.includes("title") && draft.title.trim() === "") {
      setError({ message: "Tiêu đề không được để trống.", field: "title" });
      return;
    }
    setError(null);
    setEdited(Object.keys(next).length > 0 ? next : null);
    setSelected(target.option_id);
    setEditing(false);
  };

  const confirm = () => {
    if (!selected || status !== "idle" || expired) return;
    setStatus("submitting");
    setError(null);
    onConfirm(consent.toolCallId, selected, edited)
      .catch((reason: unknown) => {
        if (reason instanceof ConfirmationRejectedError) {
          setError({ message: reason.message, field: reason.field });
          if (reason.field === "title" || reason.field === "description" || reason.field === "discount_pct" || reason.field === "end_date") {
            startEdit();
          }
        } else {
          setError({ message: "Không gửi được xác nhận. Vui lòng thử lại.", field: null });
        }
      })
      .finally(() => setStatus("idle"));
  };

  const title = isPhoto
    ? "Thay ảnh bìa: chọn rồi xác nhận"
    : isRevert
      ? "Khôi phục về nội dung cũ: chọn rồi xác nhận"
      : isPromotion
        ? "Juli đề xuất khuyến mãi sau: chọn rồi xác nhận"
        : "Juli đề xuất thay đổi sau: chọn rồi xác nhận";
  const confirmLabel = isPhoto
    ? "Xác nhận thay ảnh"
    : isRevert
      ? "Xác nhận khôi phục"
      : kind === "create"
        ? "Xác nhận tạo sản phẩm"
        : isPromotion
          ? "Xác nhận tạo khuyến mãi"
          : "Xác nhận thay đổi này";

  return (
    <div className="qv-consent" data-testid="consent-block">
      <div className="qv-consent__head">
        <span className="qv-consent__title">{title}</span>
        {validity && !isPhoto && !isRevert ? <span className="qv-consent__validity">{validity}</span> : null}
      </div>

      {editing ? (
        <div className="qv-edit" data-testid="edit-panel">
          {isPromotion ? (
            <>
              <label className="qv-edit__label">
                Mức giảm (%)
                <input
                  aria-invalid={error?.field === "discount_pct" || undefined}
                  className="qv-edit__input"
                  inputMode="numeric"
                  onChange={(event) => setDraft((d) => ({ ...d, discount: event.target.value }))}
                  type="text"
                  value={draft.discount}
                  {...write()}
                />
              </label>
              <label className="qv-edit__label">
                Ngày kết thúc
                <input
                  aria-invalid={error?.field === "end_date" || undefined}
                  className="qv-edit__input"
                  onChange={(event) => setDraft((d) => ({ ...d, endDate: event.target.value }))}
                  type="date"
                  value={draft.endDate}
                  {...write()}
                />
              </label>
            </>
          ) : null}
          {editable.includes("title") ? (
            <label className="qv-edit__label">
              Tiêu đề (bạn sửa)
              <input
                aria-invalid={error?.field === "title" || undefined}
                className="qv-edit__input"
                onChange={(event) => setDraft((d) => ({ ...d, title: event.target.value }))}
                type="text"
                value={draft.title}
                {...write()}
              />
            </label>
          ) : null}
          {editable.includes("description") ? (
            <label className="qv-edit__label">
              Mô tả (bạn sửa)
              <textarea
                aria-invalid={error?.field === "description" || undefined}
                className="qv-edit__textarea"
                onChange={(event) => setDraft((d) => ({ ...d, description: event.target.value }))}
                rows={4}
                value={draft.description}
                {...write()}
              />
            </label>
          ) : null}
          <div className="qv-edit__help">
            {isPromotion
              ? "Juli kiểm tra mức giảm theo quy tắc của shop và ngày kết thúc (tối đa 30 ngày) trước khi tạo. Juli tạo đúng giá trị bạn sửa."
              : "Juli kiểm tra độ dài và từ cấm theo quy tắc của bạn trước khi cho lưu. Juli sẽ ghi đúng nội dung bạn sửa."}
          </div>
          {error ? (
            <p className="qv-edit__error" role="alert">
              {error.message}
            </p>
          ) : null}
          <div className="qv-edit__actions">
            <button className="qv-btn qv-btn--secondary qv-btn--small" onClick={cancelEdit} type="button" {...write()}>
              Huỷ sửa
            </button>
            <button className="qv-btn qv-btn--blue qv-btn--small" onClick={saveEdit} type="button" {...write()}>
              Lưu bản sửa
            </button>
          </div>
        </div>
      ) : (
        <>
          {options.map((option) => {
            const pressed = selected === option.option_id;
            if (isPhoto) {
              const fromChange = photoUrls(option.proposed_change);
              const urls = { before: runPhotos?.before ?? fromChange.before, after: runPhotos?.after ?? fromChange.after };
              return (
                <button
                  aria-pressed={pressed}
                  className="qv-option qv-option--photo"
                  key={option.option_id}
                  onClick={() => setSelected(pressed ? null : option.option_id)}
                  type="button"
                  {...write(expired)}
                >
                  <span className="qv-photo">
                    <span className="qv-photo__frame">
                      {/* eslint-disable-next-line @next/next/no-img-element -- seller / TikTok image URLs, not optimisable assets */}
                      {urls.before ? <img alt="Ảnh bìa hiện tại" src={urls.before} /> : "[Ảnh hiện tại]"}
                    </span>
                    <span className="qv-photo__caption">Hiện tại</span>
                  </span>
                  <span className="qv-photo">
                    <span className="qv-photo__frame qv-photo__frame--new">
                      {/* eslint-disable-next-line @next/next/no-img-element -- seller / TikTok image URLs, not optimisable assets */}
                      {urls.after ? <img alt="Ảnh bạn gửi" src={urls.after} /> : "[Ảnh bạn gửi]"}
                    </span>
                    <span className="qv-photo__caption qv-photo__caption--new">Mới</span>
                  </span>
                </button>
              );
            }
            const change =
              pressed && edited ? { ...option.proposed_change, ...edited } : option.proposed_change;
            const rows = consentRows(change, { revert: isRevert, productName, card, create: kind === "create", promotion: isPromotion });
            return (
              <button
                aria-pressed={pressed}
                className={`qv-option${isRevert ? " qv-option--revert" : ""}`}
                key={option.option_id}
                onClick={() => setSelected(pressed ? null : option.option_id)}
                type="button"
                {...write(expired)}
              >
                {pressed && edited ? <span className="qv-edited">Bạn đã sửa</span> : null}
                {rows.map((row, index) => (
                  <RowLines first={index === 0} key={row.field} row={row} />
                ))}
              </button>
            );
          })}
          {canEdit ? (
            <button className="qv-edit-link" onClick={startEdit} type="button" {...write(expired)}>
              {isPromotion ? "✎ Sửa mức giảm hoặc ngày kết thúc" : "✎ Sửa nội dung trước khi áp dụng"}
            </button>
          ) : null}
        </>
      )}

      {error && !editing ? (
        <p className="qv-inline-error" role="alert">
          {error.message}
        </p>
      ) : null}

      <div className="qv-consent__actions">
        <button
          className="qv-btn qv-btn--secondary"
          onClick={() => {
            if (isRevert) {
              setStatus("submitting");
              void onCancelRevert().finally(() => setStatus("idle"));
            } else {
              onSkip();
            }
          }}
          type="button"
          {...write(status !== "idle")}
        >
          {isRevert ? "Không hoàn tác nữa" : "Không thực hiện"}
        </button>
        <button
          className="qv-btn qv-btn--primary"
          onClick={confirm}
          type="button"
          {...write(!selected || status !== "idle" || editing || expired)}
        >
          {status === "submitting" ? "Đang gửi…" : confirmLabel}
        </button>
      </div>
    </div>
  );
}

function RowLines({ row, first }: { readonly row: ReturnType<typeof consentRows>[number]; readonly first: boolean }) {
  return (
    <>
      <span className={`qv-option__field${first ? "" : " qv-option__field--next"}`}>{row.label}</span>
      {row.before !== null ? (
        <span className={`qv-option__before${row.strikeBefore ? " qv-option__before--strike" : ""}`}>
          <span className="qv-sr">Trước: </span>
          {row.before}
        </span>
      ) : null}
      <span className={`qv-option__after${row.strongAfter ? " qv-option__after--strong" : ""}`}>
        <span className="qv-sr">Sau: </span>
        {row.after}
      </span>
    </>
  );
}

// -- photo request (RunPhoto.dc.html) ------------------------------------------------------

function PhotoRequest({
  checks,
  state,
  onUpload,
}: {
  readonly checks: readonly PhotoCheck[] | null;
  readonly state: PhotoState;
  readonly onUpload: (file: File) => Promise<void>;
}) {
  const write = useRunControl();
  const input = useRef<HTMLInputElement | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const uploading = state.status === "uploading";
  return (
    <div className="qv-upload" data-testid="photo-request">
      <div className="qv-upload__text">
        <span className="qv-consent__title">Juli cần ảnh bìa mới từ bạn</span>
        <span className="qv-upload__lede">Juli không tự chọn hay tạo ảnh cho sản phẩm. Ảnh cần đạt:</span>
        <ul className="qv-upload__list">
          <li>Tỷ lệ 1:1, tối thiểu 800 × 800 px</li>
          <li>Nền trắng hoặc trơn, không chữ, không khung viền</li>
          <li>Sản phẩm chiếm từ 70 % khung ảnh</li>
        </ul>
        <span className="qv-note">Yêu cầu còn hiệu lực 3 ngày. Sau đó lượt chạy dừng, không thay đổi gì.</span>
        {checks && checks.length > 0 ? (
          <ul aria-label="Kết quả kiểm tra ảnh" className="qv-checks" data-testid="photo-checks">
            {checks.map((check) => (
              <li className={check.ok ? "qv-check--ok" : "qv-check--bad"} key={check.key}>
                {check.ok ? "✓" : "✗"} {check.label}
              </li>
            ))}
          </ul>
        ) : null}
        {localError || state.status === "error" ? (
          <p className="qv-inline-error" role="alert">
            {localError ?? (state.status === "error" ? state.message : "")}
          </p>
        ) : null}
      </div>
      <button className="qv-dropzone" onClick={() => input.current?.click()} type="button" {...write(uploading)}>
        <svg
          aria-hidden="true"
          fill="none"
          height="28"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
          viewBox="0 0 24 24"
          width="28"
        >
          <path d="M12 16V4M7 9l5-5 5 5M4 20h16" />
        </svg>
        <span className="qv-dropzone__main">{uploading ? "Đang tải ảnh lên…" : "Chọn ảnh từ máy"}</span>
        <span className="qv-dropzone__sub">JPG hoặc PNG, tối đa 5 MB</span>
      </button>
      <input
        accept="image/jpeg,image/png"
        aria-label="Chọn ảnh bìa"
        data-testid="photo-input"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          if (!PHOTO_TYPES.has(file.type)) {
            setLocalError("Ảnh cần là JPG hoặc PNG.");
            return;
          }
          if (file.size > MAX_PHOTO_BYTES) {
            setLocalError("Ảnh lớn hơn 5 MB. Vui lòng chọn ảnh nhỏ hơn.");
            return;
          }
          setLocalError(null);
          void onUpload(file);
        }}
        ref={input}
        type="file"
        {...write()}
      />
    </div>
  );
}

// -- Seller Center checklist (RunManual.dc.html) -----------------------------------------------

function SellerGuide({
  instructions,
  applied,
  narration,
  onApplied,
  onSkip,
}: {
  readonly instructions: LoadState<SellerInstructions> | null;
  readonly applied: { readonly busy: boolean; readonly error: string | null };
  readonly narration: string | null;
  readonly onApplied: () => Promise<void>;
  readonly onSkip: () => void;
}) {
  const write = useWriteControl();
  const steps = instructions?.status === "ready" ? instructions.data.steps : [];
  const [ticks, setTicks] = useState<readonly boolean[]>([]);
  const all = steps.length > 0 && steps.every((_, index) => ticks[index]);
  const notFound = narration && /Chưa tìm thấy/.test(narration) ? narration : null;
  return (
    <div className="qv-guide" data-testid="seller-guide">
      <div className="qv-guide__head">
        <span className="qv-guide__title">
          {steps.length > 0 ? `Làm theo ${steps.length} bước trên Seller Center` : "Làm theo các bước trên Seller Center"}
        </span>
        {instructions?.status === "ready" && instructions.data.deep_link ? (
          <a className="qv-link qv-guide__link" href={instructions.data.deep_link} rel="noreferrer" target="_blank">
            Mở Seller Center ↗
          </a>
        ) : null}
      </div>
      {notFound ? (
        <p className="qv-inline-error" role="status">
          {notFound}
        </p>
      ) : null}
      {instructions === null || instructions.status === "loading" ? (
        <p className="qv-status-line" role="status">
          Đang tải hướng dẫn…
        </p>
      ) : instructions.status === "error" ? (
        <p className="qv-inline-error" role="alert">
          Không tải được hướng dẫn. Vui lòng thử lại.
        </p>
      ) : (
        <ol className="qv-guide__list">
          {steps.map((text, index) => (
            <li key={index}>
              <label className="qv-guide__item">
                <input
                  checked={Boolean(ticks[index])}
                  onChange={() =>
                    setTicks((current) => {
                      const next = steps.map((_, i) => Boolean(current[i]));
                      next[index] = !next[index];
                      return next;
                    })
                  }
                  type="checkbox"
                  {...write()}
                />
                <span>
                  <strong>{index + 1}.</strong> {text}
                </span>
              </label>
            </li>
          ))}
        </ol>
      )}
      {instructions?.status === "ready" && instructions.data.summary ? (
        <div className="qv-guide__summary">{instructions.data.summary}</div>
      ) : null}
      {applied.error ? (
        <p className="qv-inline-error" role="alert">
          {applied.error}
        </p>
      ) : null}
      <div className="qv-guide__actions">
        <button className="qv-btn qv-btn--secondary" onClick={onSkip} type="button" {...write(applied.busy)}>
          Không áp dụng nữa
        </button>
        <button
          className="qv-btn qv-btn--primary"
          onClick={() => {
            if (all) void onApplied();
          }}
          type="button"
          {...write(!all || applied.busy)}
        >
          Tôi đã áp dụng
        </button>
      </div>
    </div>
  );
}

// -- done (Run / RunPhoto / RunManual / Revert) -------------------------------------------------

/** P64 (D73.3 / D73.4): the partner account's results on Juli's TikTok sandbox shop. */
const CREATE_DONE_TITLE = "Đã tạo sản phẩm trên TikTok";
const CREATE_DONE_FALLBACK = "TikTok đã nhận sản phẩm mới; trạng thái hiện ở bước Tạo sản phẩm trên TikTok.";
/** P65 (D74): the promotion as TikTok read it back; no ROI claim on a shop with no buyers. */
const PROMOTION_DONE_TITLE = "Đã tạo khuyến mãi trên TikTok";
const PROMOTION_DONE_FALLBACK = "TikTok đã nhận khuyến mãi mới; trạng thái hiện ở bước Tạo khuyến mãi trên TikTok.";
export const PROMOTION_NO_ROI_TEXT =
  "Shop sandbox không có người mua thật nên Juli không đo doanh số hay hiệu quả (ROI) của khuyến mãi này.";
const SANDBOX_DONE_TITLE = "Đã ghi lên shop sandbox TikTok của Juli";
const SANDBOX_DONE_TEXT = "Thay đổi đã được ghi lên shop sandbox. Shop sandbox không có lượt xem nên Juli không đo kết quả.";

function DonePanel({
  kind,
  card,
  changes,
  changedLabels,
  day7,
  day14,
  measureHref,
  onOpenMeasure,
  onRevert,
  revertBusy,
  revertReasonLabel,
  simulated,
  writeSummary = null,
}: {
  readonly kind: RunKind;
  readonly card: CardView | null;
  readonly changes: RunChanges | null;
  readonly changedLabels: readonly string[];
  readonly day7: string | null;
  readonly day14: string | null;
  readonly measureHref: string;
  readonly onOpenMeasure: (event: React.MouseEvent<HTMLAnchorElement>) => void;
  readonly onRevert: () => void;
  readonly revertBusy: boolean;
  readonly revertReasonLabel: string | null;
  /** P61-B: the run wrote to the test shop, not the seller's shop. */
  readonly simulated: boolean;
  /** The write step's one-line result (P64: TikTok's read-back of the new product). */
  readonly writeSummary?: string | null;
}) {
  const sellerHref = useSellerHref();
  const write = useWriteControl();
  const runActions = useRunActions();
  const sandboxShop = useSandboxReviewer();
  const sandboxReviewer = runActions || sandboxShop;
  if (kind === "create") {
    // P64 (D73.3): the new listing as TikTok confirmed it (id, status, time).
    return (
      <div className="qv-done qv-done--tight" data-testid="run-done">
        <div className="qv-done__title">{CREATE_DONE_TITLE}</div>
        <div className="qv-done__text" data-testid="create-read-back">
          {writeSummary ?? CREATE_DONE_FALLBACK}
        </div>
      </div>
    );
  }
  if (kind === "promotion") {
    return (
      <div className="qv-done qv-done--tight" data-testid="run-done">
        <div className="qv-done__title">{PROMOTION_DONE_TITLE}</div>
        <div className="qv-done__text" data-testid="promotion-read-back">
          {writeSummary ?? PROMOTION_DONE_FALLBACK}
        </div>
        <div className="qv-done__text" data-testid="promotion-no-roi">
          {PROMOTION_NO_ROI_TEXT}
        </div>
      </div>
    );
  }
  if (simulated && sandboxReviewer && kind !== "revert") {
    // P64 (D73.4): the partner account's shop IS Juli's sandbox shop — the write landed there.
    return (
      <div className="qv-done qv-done--tight" data-testid="run-done">
        <div className="qv-done__title">{SANDBOX_DONE_TITLE}</div>
        <div className="qv-done__text">{writeSummary ?? SANDBOX_DONE_TEXT}</div>
      </div>
    );
  }
  if (simulated && kind !== "revert") {
    return (
      <div className="qv-done qv-done--tight" data-testid="run-done">
        <div className="qv-done__title">{SIMULATED_DONE_TITLE}</div>
        <div className="qv-done__text">{SIMULATED_DONE_TEXT}</div>
      </div>
    );
  }
  if (kind === "revert") {
    const fields = changedLabels.length > 0 ? changedLabels.join(" / ") : "này";
    const lines = [
      `Kết quả đo của thay đổi này dừng lại và được ghi là "Đã hoàn tác". Juli không đề xuất lại thay đổi ${fields} cho sản phẩm này trong 7 ngày.`,
    ];
    const small = "Một lần hoàn tác không thể hoàn tác tiếp. Muốn dùng lại nội dung mới, chờ đề xuất sau.";
    const title = "Hoàn tác hoàn thành · đã khôi phục nội dung cũ";
    if (revertReasonLabel) {
      return (
        <div data-testid="run-done">
          <ReasonDone lines={lines} reason={reasonOption(REVERT_REASONS, revertReasonLabel)} small={small} title={title} />
        </div>
      );
    }
    return (
      <div className="qv-done qv-done--tight" data-testid="run-done">
        <div className="qv-done__title">{title}</div>
        <div className="qv-done__text">{lines[0]}</div>
        <div className="qv-done__small">{small}</div>
      </div>
    );
  }
  const dates = day7 && day14 ? { d7: dateText(day7), d14: dateText(day14) } : null;
  const kpi = card?.kpiPairText && card.kpiLabel ? `${card.kpiLabel.split(/[\s-]/)[0]} ${card.kpiPairText}` : null;
  let title = "Đã áp dụng · thẻ chuyển sang Đo lường";
  let text = `Đã đổi: ${fieldList(changedLabels) || "nội dung"}. Giá trị cũ đã được lưu.${
    dates ? ` Đo sơ bộ ${dates.d7} (ngày 7), chốt ${dates.d14} (ngày 14).` : ""
  }`;
  if (kind === "photo") {
    title = "Đã thay ảnh bìa · thẻ chuyển sang Đo lường";
    text = `Ảnh cũ đã được lưu.${kpi ? ` Chỉ số mục tiêu: ${kpi}.` : ""}${dates ? ` Đo sơ bộ ${dates.d7}, chốt ${dates.d14}.` : ""}`;
  }
  if (kind === "manual") {
    title = "Đã xác nhận trên TikTok · thẻ chuyển sang Đo lường";
    text = `${kpi ? `Chỉ số mục tiêu: ${kpi}. ` : ""}Tính từ ngày khuyến mãi bắt đầu: đo sơ bộ ngày 7, chốt ngày 14.`;
  }
  const revert = changes?.revert ?? null;
  return (
    <div className="qv-done" data-testid="run-done">
      <div className="qv-done__title">{title}</div>
      <div className="qv-done__text">{text}</div>
      <div className="qv-done__actions">
        <a className="qv-link" href={sellerHref(measureHref)} onClick={onOpenMeasure}>
          Xem Đo lường ›
        </a>
        {kind === "manual" ? (
          <span className="qv-done__note">
            Không có nút Hoàn tác: muốn dừng, bạn tắt khuyến mãi trên Seller Center, Juli tự ghi nhận.
          </span>
        ) : changes && !changes.reverts_run_id && changes.changes.length > 0 ? (
          <button
            aria-describedby={revert && !revert.available && revert.message ? "qv-revert-why" : undefined}
            className="qv-btn qv-btn--secondary"
            onClick={onRevert}
            type="button"
            {...write(!revert?.available || revertBusy)}
          >
            {revertBusy ? "Đang tạo lượt hoàn tác…" : kind === "photo" ? "Hoàn tác (dùng lại ảnh cũ)" : "Hoàn tác"}
          </button>
        ) : null}
      </div>
      {revert && !revert.available && revert.message && kind !== "manual" ? (
        <div className="qv-note" id="qv-revert-why">
          {revert.message}
        </div>
      ) : null}
    </div>
  );
}
