/**
 * The partner trial account's simulated Duyệt → Thực thi over the bundled
 * sample shop (fast track P32-D, D42 amendment 2026-10-15). With no reference
 * shop pinned the reviewer sees "Cửa hàng Mẫu Hoa Mai" (P11/P13): this builds
 * the same response `POST …/reviewer/decisions/{id}/simulate` returns
 * (contract p32-reviewer-access.md §4, a port of the backend's
 * `services/reviewer/simulation.py`) from the sample cards, in memory. No
 * request, nothing written, no run created in the sample store either.
 */

import { SAMPLE_CARDS, SAMPLE_CONTENT_CARDS, sampleContentDecision, sampleDecision } from "../quyet-dinh/sample-data";
import { REVIEWER_SIMULATED_LABEL, REVIEWER_SIMULATION_NOTES } from "./copy";
import type { SimulatedField, SimulatedRequest, SimulationResult, SimulationStep } from "./simulation-types";

/** `integrations.tiktok.constants.product_edit_path("{product_id}")` (D13). */
export const SAMPLE_PRODUCT_EDIT_PATH = "/product/202309/products/{product_id}";
const NOTE_DRAFT_AFTER_APPROVAL = "Juli soạn nội dung mới sau khi duyệt";
const STEP_LABELS = [
  ["approve", "Duyệt"],
  ["execute", "Thực thi"],
] as const;

/** P41 (D47.7): one short line per executor, the same as the backend's `_NOTES`. */
const NOTES = REVIEWER_SIMULATION_NOTES;
/** The "Sau" cell when the card has no proposal yet (the backend's `_AFTER_DEFAULT`). */
const AFTER_DEFAULT: Readonly<Record<string, string>> = {
  juli: NOTE_DRAFT_AFTER_APPROVAL,
  juli_with_photo: "Ảnh mới bạn gửi, sau khi Juli kiểm tra",
  juli_drafts: "Juli soạn kịch bản sau khi duyệt",
  seller_center: "Bạn áp dụng trên Seller Center",
};

type Loose = Record<string, unknown>;

function obj(value: unknown): Loose {
  return value && typeof value === "object" ? (value as Loose) : {};
}

function str(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function request(executor: string, field: string): SimulatedRequest | null {
  if (executor === "juli") {
    return { method: "PUT", path: SAMPLE_PRODUCT_EDIT_PATH, operation: "update_product_listing", fields: [field] };
  }
  if (executor === "juli_with_photo") {
    return {
      method: "PUT",
      path: SAMPLE_PRODUCT_EDIT_PATH,
      operation: "upload_product_image + update_product_listing",
      fields: [field],
    };
  }
  return null;
}

/** The simulated response for one decision item (pure; mirrors the backend's `simulate`). */
export function simulateItem(item: unknown, step: SimulationStep): SimulationResult {
  const recommendation = obj(obj(item).recommendation);
  const card = obj(recommendation.card);
  const diagnosis = obj(recommendation.diagnosis);
  const lever = obj(card.lever);
  const executor = str(lever.executor) ?? "seller_center";
  const changeFields = Array.isArray(card.change_fields) ? card.change_fields.map(obj) : [];
  const firstField = str(changeFields[0]?.field) ?? str(lever.code) ?? "";
  const proposals = new Map(
    (Array.isArray(card.before_after) ? card.before_after.map(obj) : []).map((p) => [str(p.field) ?? "", p]),
  );
  const fields: SimulatedField[] = changeFields.map((entry) => {
    const code = str(entry.field) ?? "";
    const proposal = proposals.get(code) ?? {};
    return {
      field: code,
      label: str(entry.label) ?? code,
      before: str(proposal.before),
      after: str(proposal.after) ?? AFTER_DEFAULT[executor] ?? NOTE_DRAFT_AFTER_APPROVAL,
    };
  });
  const done = step === "approve" ? new Set(["approve"]) : new Set(["approve", "execute"]);
  return {
    simulated: true,
    step,
    action_card_id: String(obj(item).id ?? ""),
    label: REVIEWER_SIMULATED_LABEL,
    steps: STEP_LABELS.map(([key, label]) => ({ key, label, done: done.has(key) })),
    change: {
      executor,
      lever: { code: str(lever.code) ?? "", label: str(lever.label) ?? "" },
      product: {
        title: str(card.product_title) ?? str(diagnosis.product_title),
        tiktok_product_id: str(diagnosis.tiktok_product_id),
      },
      request: request(executor, firstField),
      fields,
      note: NOTES[executor] ?? NOTES.seller_center,
    },
    enqueued: false,
    tiktok_write: false,
  };
}

/** A sample card's simulation; rejects with `{status: 404}` for an unknown card. */
export function simulateSampleDecision(cardId: string, step: SimulationStep): Promise<SimulationResult> {
  const now = Date.now();
  const spec = SAMPLE_CARDS.find((card) => card.id === cardId);
  const content = spec ? null : SAMPLE_CONTENT_CARDS.find((card) => card.id === cardId);
  const item = spec ? sampleDecision(spec, now) : content ? sampleContentDecision(content, now) : null;
  if (!item) return Promise.reject(Object.assign(new Error("sample card not found"), { status: 404 }));
  return Promise.resolve(simulateItem(item, step));
}
