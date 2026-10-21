"use client";

import { useEffect, useId, useState } from "react";

import {
  SANDBOX_APPROVE_LABEL,
  SANDBOX_CONFIRMED_PREFIX,
  SANDBOX_EXECUTE_LABEL,
  SANDBOX_FIELD_LABELS,
  SANDBOX_INTENDED_NOTE,
  sandboxErrorCopy,
} from "../../lib/reviewer/copy";
import {
  approveSandboxDecision,
  executeSandboxDecision,
  type ExecuteBody,
  type SandboxExecution,
  type SandboxOptions,
  type SandboxPlan,
} from "../../lib/reviewer/sandbox-client";
import { absoluteVn } from "../reviewer/sandbox-connection-card";

/**
 * P64 (D73): the partner reviewer's REAL Duyệt → Thực thi on the live TikTok
 * sandbox shop. "Duyệt" fetches the planned change (nothing written yet);
 * "Thực thi" writes the listing edit (title / description, or a new cover
 * image) and shows TikTok's read-back: each field before → after and when
 * TikTok confirmed it. A field TikTok did not return stays marked
 * "chưa được TikTok xác nhận". No "Mô phỏng" wording, no `/simulate` call.
 */

export interface SandboxDecisionClient {
  readonly approve: (cardId: string) => Promise<SandboxPlan>;
  readonly execute: (cardId: string, body: ExecuteBody) => Promise<SandboxExecution>;
}

export function createSandboxDecisionClient(options: SandboxOptions): SandboxDecisionClient {
  return {
    approve: (cardId) => approveSandboxDecision(cardId, options),
    execute: (cardId, body) => executeSandboxDecision(cardId, body, options),
  };
}

type State =
  | { status: "approving" }
  | { status: "planned"; plan: SandboxPlan; error: string | null }
  | { status: "executing"; plan: SandboxPlan }
  | { status: "done"; plan: SandboxPlan; execution: SandboxExecution }
  | { status: "failed"; message: string };

function errorMessage(error: unknown): string {
  const e = error as { status?: number; code?: string | null; tiktokCode?: number | null } | null;
  return sandboxErrorCopy(e?.code ?? null, e?.tiktokCode ?? null, e?.status ?? 0);
}

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      resolve(result.slice(result.indexOf(",") + 1));
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function planned(plan: SandboxPlan, field: string): string {
  const after = plan.change.fields.find((f) => f.field === field)?.after;
  return after ?? "";
}

export function SandboxDecisionDialog({
  cardId,
  onClose,
  client,
}: {
  readonly cardId: string;
  readonly onClose: () => void;
  readonly client: SandboxDecisionClient;
}) {
  const titleId = useId();
  const [state, setState] = useState<State>({ status: "approving" });
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [image, setImage] = useState<string | null>(null);
  const [imageName, setImageName] = useState<string | null>(null);

  const approve = () => {
    setState({ status: "approving" });
    client.approve(cardId).then(
      (plan) => {
        setTitle(planned(plan, "title"));
        setDescription(planned(plan, "description"));
        setState({ status: "planned", plan, error: null });
      },
      (error: unknown) => setState({ status: "failed", message: errorMessage(error) }),
    );
  };

  useEffect(() => {
    const timer = window.setTimeout(approve, 0);
    return () => window.clearTimeout(timer);
    // One approve per opened card.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardId]);

  const plan = state.status === "planned" || state.status === "executing" || state.status === "done" ? state.plan : null;
  const lever = plan?.change.lever.code;
  const editsTitle = lever === "title";
  const editsDescription = lever === "description";

  const execute = () => {
    if (!plan) return;
    const body: ExecuteBody = {
      ...(editsTitle && title.trim() ? { title: title.trim() } : {}),
      ...(editsDescription && description.trim() ? { description: description.trim() } : {}),
      ...(image ? { image_base64: image } : {}),
    };
    setState({ status: "executing", plan });
    client.execute(cardId, body).then(
      (execution) => setState({ status: "done", plan, execution }),
      (error: unknown) => setState({ status: "planned", plan, error: errorMessage(error) }),
    );
  };

  const onPickImage = (file: File | undefined) => {
    if (!file) {
      setImage(null);
      setImageName(null);
      return;
    }
    readBase64(file).then(
      (data) => {
        setImage(data);
        setImageName(file.name);
      },
      () => {
        setImage(null);
        setImageName(null);
      },
    );
  };

  const done = state.status === "done" ? state : null;
  const confirmedAt = done ? absoluteVn(done.execution.read_back.confirmed_at) : null;
  const canExecute = plan?.executable === true && (!plan.requires_image || image !== null);

  return (
    <div className="qv-overlay" data-testid="sandbox-decision">
      <div aria-labelledby={titleId} aria-modal="true" className="qv-dialog reviewer-sim" role="dialog">
        <h3 className="qv-dialog__title" id={titleId}>
          {done ? "Đã ghi lên TikTok" : plan ? "Thay đổi Juli sẽ ghi lên TikTok" : SANDBOX_APPROVE_LABEL}
        </h3>

        <ol className="reviewer-sim__steps">
          <li data-done={plan ? "true" : "false"}>{plan ? "✓ " : ""}{SANDBOX_APPROVE_LABEL}</li>
          <li data-done={done ? "true" : "false"}>{done ? "✓ " : ""}{SANDBOX_EXECUTE_LABEL}</li>
        </ol>

        {plan ? (
          <dl className="reviewer-sim__facts">
            <dt>Thao tác</dt>
            <dd>{plan.change.lever.label}</dd>
            {plan.change.product.title ? (
              <>
                <dt>Sản phẩm</dt>
                <dd>{plan.change.product.title}</dd>
              </>
            ) : null}
          </dl>
        ) : null}

        {plan && !done ? (
          <>
            {plan.change.fields.length > 0 ? (
              <table className="reviewer-sim__fields" data-testid="sandbox-plan">
                <thead>
                  <tr>
                    <th scope="col">Mục</th>
                    <th scope="col">Trước</th>
                    <th scope="col">Sau</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.change.fields.map((field) => (
                    <tr key={field.field}>
                      <th scope="row">{field.label}</th>
                      <td>{field.before ?? "—"}</td>
                      <td>{field.after ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            {plan.executable && editsTitle ? (
              <label className="qv-field">
                Tiêu đề mới
                <input onChange={(e) => setTitle(e.target.value)} type="text" value={title} />
              </label>
            ) : null}
            {plan.executable && editsDescription ? (
              <label className="qv-field">
                Mô tả mới
                <textarea onChange={(e) => setDescription(e.target.value)} rows={5} value={description} />
              </label>
            ) : null}
            {plan.requires_image ? (
              <label className="qv-field">
                Ảnh bìa mới
                <input accept="image/*" onChange={(e) => onPickImage(e.target.files?.[0])} type="file" />
                {imageName ? <span className="text-muted">{imageName}</span> : null}
              </label>
            ) : null}
            {!plan.executable ? (
              <p className="qv-dialog__body">Thao tác này bạn tự áp dụng; Juli không ghi gì lên TikTok.</p>
            ) : null}
          </>
        ) : null}

        {done ? (
          <div className="reviewer-sim__change" data-testid="sandbox-result">
            <table className="reviewer-sim__fields">
              <thead>
                <tr>
                  <th scope="col">Mục</th>
                  <th scope="col">Trước</th>
                  <th scope="col">Sau</th>
                </tr>
              </thead>
              <tbody>
                {done.execution.read_back.fields.map((field) => (
                  <tr data-after-source={field.after_source} key={field.field}>
                    <th scope="row">{SANDBOX_FIELD_LABELS[field.field] ?? field.field}</th>
                    <td>{field.before ?? "—"}</td>
                    <td>
                      {field.after ?? "—"}
                      {field.after_source === "intended" ? (
                        <span className="text-muted" data-testid="sandbox-intended"> ({SANDBOX_INTENDED_NOTE})</span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="qv-dialog__body" data-testid="sandbox-confirmed-at">
              {SANDBOX_CONFIRMED_PREFIX} {confirmedAt ?? done.execution.read_back.confirmed_at}
            </p>
          </div>
        ) : null}

        {state.status === "approving" ? (
          <p className="qv-status-line" role="status">
            Đang duyệt…
          </p>
        ) : null}
        {state.status === "executing" ? (
          <p className="qv-status-line" role="status">
            Đang ghi lên TikTok…
          </p>
        ) : null}
        {state.status === "failed" ? (
          <p className="qv-inline-error" role="alert">
            {state.message}
          </p>
        ) : null}
        {state.status === "planned" && state.error ? (
          <p className="qv-inline-error" role="alert">
            {state.error}
          </p>
        ) : null}

        <div className="qv-dialog__actions">
          {state.status === "failed" ? (
            <button className="qv-btn qv-btn--primary" onClick={approve} type="button">
              Thử lại
            </button>
          ) : null}
          {plan && !done ? (
            <button className="qv-btn qv-btn--primary" disabled={!canExecute || state.status === "executing"} onClick={execute} type="button">
              {SANDBOX_EXECUTE_LABEL}
            </button>
          ) : null}
          <button className="qv-btn qv-btn--secondary" onClick={onClose} type="button">
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
}
