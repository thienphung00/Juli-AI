"use client";

import { useRef, useState } from "react";

import type { CardView } from "../../lib/quyet-dinh/card-model";
import { consentRows, editableFields, photoUrls, proposedText } from "../../lib/quyet-dinh/consent-model";
import { dateText, validityText } from "../../lib/quyet-dinh/p10-format";
import type { PhotoCheck, QdRun, SellerInstructions } from "../../lib/quyet-dinh/p10-types";
import type { ReasonChoice } from "../../lib/quyet-dinh/reasons";
import { runChip, runningNote, type RunPhase } from "../../lib/quyet-dinh/run-model";
import type { RunKind, RunTimeline } from "../../lib/quyet-dinh/timeline";
import type { RunChanges } from "../../lib/quyet-dinh/types";
import { RUN_TERMINAL_STATE_COPY, RUN_TERMINAL_STATE_UNKNOWN_COPY } from "../../lib/run-ledger/copy";
import { resolveRunTerminalState } from "../../lib/run-ledger/terminal-state";
import { ConfirmationRejectedError } from "../../lib/run-surface/confirmation-decision";
import { ReasonDialog, SKIP_DIALOG_BODY, revertDialogBody } from "./reason-dialog";
import { Chevron, StageChips, StepList, timelineRows } from "./run-steps";

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
  readonly onConfirm: (toolCallId: string, optionId: string, edited: Readonly<{ title?: string; description?: string }> | null) => Promise<void>;
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
  const [dialogBusy, setDialogBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const chip = runChip(run, kind, phase);
  const headingId = `run-${run.id}`;
  const changedLabels =
    changes && changes.changes.length > 0
      ? changes.changes.map((change) => change.label)
      : (card?.changeLabels ?? []);
  const note = runningNote(kind, phase, timeline.narration);
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
            <div className="qv-running" role="status">
              <span>{note}</span>
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
            />
          ) : null}

          {props.revertConflict ? <ConflictBox message={props.revertConflict} /> : null}
          {props.revertError ? (
            <p className="qv-inline-error" role="alert">
              {props.revertError}
            </p>
          ) : null}

          {phase === "declined" ? <div className="qv-grey">{declinedText(kind)}</div> : null}
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
            .then(() => setDialog(null))
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
  const options =
    consent.options.length > 0
      ? consent.options
      : [{ option_id: "default", proposed_change: consent.proposedChange, rationale: "", params_sha: "" }];
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [edited, setEdited] = useState<{ title?: string; description?: string } | null>(null);
  const [draft, setDraft] = useState<{ title: string; description: string }>({ title: "", description: "" });
  const [status, setStatus] = useState<"idle" | "submitting">("idle");
  const [error, setError] = useState<{ message: string; field: string | null } | null>(null);
  const isPhoto = kind === "photo" || consent.toolName === "upload_product_image";
  const isRevert = kind === "revert";
  const validity = validityText(consent.expiresAt, nowMs);
  const expired = validity === "Đã hết hiệu lực";
  const target = options.find((option) => option.option_id === selected) ?? options[0];
  const editable = !isPhoto && !isRevert ? editableFields(target.proposed_change) : [];

  const startEdit = () => {
    setDraft({
      title: edited?.title ?? proposedText(target.proposed_change.title) ?? "",
      description: edited?.description ?? proposedText(target.proposed_change.description) ?? "",
    });
    setEditing(true);
  };

  const saveEdit = () => {
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
          if (reason.field === "title" || reason.field === "description") {
            startEdit();
          }
        } else {
          setError({ message: "Không gửi được xác nhận. Vui lòng thử lại.", field: null });
        }
      })
      .finally(() => setStatus("idle"));
  };

  const title = isPhoto
    ? "Thay ảnh bìa — chọn rồi xác nhận"
    : isRevert
      ? "Khôi phục về nội dung cũ — chọn rồi xác nhận"
      : "Juli đề xuất thay đổi sau — chọn rồi xác nhận";
  const confirmLabel = isPhoto ? "Xác nhận thay ảnh" : isRevert ? "Xác nhận khôi phục" : "Xác nhận thay đổi này";

  return (
    <div className="qv-consent" data-testid="consent-block">
      <div className="qv-consent__head">
        <span className="qv-consent__title">{title}</span>
        {validity && !isPhoto && !isRevert ? <span className="qv-consent__validity">{validity}</span> : null}
      </div>

      {editing ? (
        <div className="qv-edit" data-testid="edit-panel">
          {editable.includes("title") ? (
            <label className="qv-edit__label">
              Tiêu đề (bạn sửa)
              <input
                aria-invalid={error?.field === "title" || undefined}
                className="qv-edit__input"
                onChange={(event) => setDraft((d) => ({ ...d, title: event.target.value }))}
                type="text"
                value={draft.title}
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
              />
            </label>
          ) : null}
          <div className="qv-edit__help">
            Juli kiểm tra độ dài và từ cấm theo quy tắc của bạn trước khi cho lưu. Juli sẽ ghi đúng nội dung bạn sửa.
          </div>
          {error ? (
            <p className="qv-edit__error" role="alert">
              {error.message}
            </p>
          ) : null}
          <div className="qv-edit__actions">
            <button className="qv-btn qv-btn--secondary qv-btn--small" onClick={() => setEditing(false)} type="button">
              Huỷ sửa
            </button>
            <button className="qv-btn qv-btn--blue qv-btn--small" onClick={saveEdit} type="button">
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
                  disabled={expired}
                  key={option.option_id}
                  onClick={() => setSelected(pressed ? null : option.option_id)}
                  type="button"
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
            const rows = consentRows(change, { revert: isRevert, productName, card });
            return (
              <button
                aria-pressed={pressed}
                className={`qv-option${isRevert ? " qv-option--revert" : ""}`}
                disabled={expired}
                key={option.option_id}
                onClick={() => setSelected(pressed ? null : option.option_id)}
                type="button"
              >
                {pressed && edited ? <span className="qv-edited">Bạn đã sửa</span> : null}
                {rows.map((row, index) => (
                  <RowLines first={index === 0} key={row.field} row={row} />
                ))}
              </button>
            );
          })}
          {editable.length > 0 ? (
            <button className="qv-edit-link" disabled={expired} onClick={startEdit} type="button">
              ✎ Sửa nội dung trước khi áp dụng
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
          disabled={status !== "idle"}
          onClick={() => {
            if (isRevert) {
              setStatus("submitting");
              void onCancelRevert().finally(() => setStatus("idle"));
            } else {
              onSkip();
            }
          }}
          type="button"
        >
          {isRevert ? "Không hoàn tác nữa" : "Không thực hiện"}
        </button>
        <button
          className="qv-btn qv-btn--primary"
          disabled={!selected || status !== "idle" || editing || expired}
          onClick={confirm}
          type="button"
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
  const input = useRef<HTMLInputElement | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const uploading = state.status === "uploading";
  return (
    <div className="qv-upload" data-testid="photo-request">
      <div className="qv-upload__text">
        <span className="qv-consent__title">Juli cần ảnh bìa mới từ bạn</span>
        <span className="qv-upload__lede">Juli không tự chọn hay tạo ảnh cho sản phẩm. Ảnh cần đạt:</span>
        <ul className="qv-upload__list">
          <li>Tỉ lệ 1:1, tối thiểu 800 × 800 px</li>
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
      <button className="qv-dropzone" disabled={uploading} onClick={() => input.current?.click()} type="button">
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
        <button className="qv-btn qv-btn--secondary" disabled={applied.busy} onClick={onSkip} type="button">
          Không áp dụng nữa
        </button>
        <button
          className="qv-btn qv-btn--primary"
          disabled={!all || applied.busy}
          onClick={() => {
            if (all) void onApplied();
          }}
          type="button"
        >
          Tôi đã áp dụng
        </button>
      </div>
    </div>
  );
}

// -- done (Run / RunPhoto / RunManual / Revert) -------------------------------------------------

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
}) {
  if (kind === "revert") {
    const fields = changedLabels.length > 0 ? changedLabels.join(" / ") : "này";
    return (
      <div className="qv-done qv-done--tight" data-testid="run-done">
        <div className="qv-done__title">Đã khôi phục nội dung cũ</div>
        <div className="qv-done__text">
          Kết quả đo của thay đổi này dừng lại và được ghi là &quot;Đã hoàn tác&quot;
          {revertReasonLabel ? ` · lý do: ${revertReasonLabel}` : ""}. Juli không đề xuất lại thay đổi {fields} cho sản phẩm này trong
          7 ngày, trừ khi số liệu đổi rõ.
        </div>
        <div className="qv-done__small">Một lần hoàn tác không thể hoàn tác tiếp. Muốn dùng lại nội dung mới, chờ đề xuất sau.</div>
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
        <a className="qv-link" href={measureHref} onClick={onOpenMeasure}>
          Xem Đo lường ›
        </a>
        {kind === "manual" ? (
          <span className="qv-done__note">
            Không có nút Hoàn tác: muốn dừng, bạn tắt khuyến mãi trên Seller Center — Juli tự ghi nhận.
          </span>
        ) : changes && !changes.reverts_run_id && changes.changes.length > 0 ? (
          <button
            aria-describedby={revert && !revert.available && revert.message ? "qv-revert-why" : undefined}
            className="qv-btn qv-btn--secondary"
            disabled={!revert?.available || revertBusy}
            onClick={onRevert}
            type="button"
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
