/**
 * Typed caveat classes (ADR-055 item 10; PRD #758 stories 41–44 and 47).
 *
 * `knownLimits` on the shared recommendation fixture table is a grab-bag: four
 * different kinds of statement concatenated into one opaque string, which is
 * why the card could never show one differently from another. This module
 * decomposes it into typed caveats and fixes one presentation rule per class,
 * so presentation is applied consistently rather than judged per string.
 *
 * | Class | Meaning | Workflows | Treatment |
 * |---|---|---|---|
 * | A `threshold-undefined` | "Juli won't invent the number" | 11/11 | Hidden — true of every workflow, so it discriminates nothing |
 * | B `fulfilment-unsupported` | capability boundary by fulfilment model | 7/11 | Hidden in the Demo, which has no shop profile and is uniformly one fulfilment model, so the statement is vacuously true. The typed data survives for multi-tenant sign-in to render as a real applicability check |
 * | C `feature-unavailable` | a genuine functional gap | 3/11 | Shown inside the reasoning expansion — it is an answer to "why?", not a standing warning |
 * | D `reassurance` | "Juli won't act without you" | 3/11 | Promoted out of limits into the Decision section as a resting trust line. It is a selling point, not a limitation |
 *
 * The distinction that must not be fumbled: "không tự **suy diễn**" (Juli will
 * not infer a number) is class A, **not** a promise that Juli will not act
 * unaided. Misfiling it as class D would hide a real limitation and wrongly
 * block repeat consent downstream.
 */

/** The four kinds of statement the known-limits blob was hiding. */
export type PlanCaveatClass =
  /** A — a threshold or policy that was never defined. */
  | "threshold-undefined"
  /** B — a capability boundary that depends on the fulfilment model. */
  | "fulfilment-unsupported"
  /** C — a functional gap that genuinely limits what the seller can do today. */
  | "feature-unavailable"
  /** D — a promise that Juli will not act without the seller. */
  | "reassurance";

export const PLAN_CAVEAT_CLASSES = [
  "threshold-undefined",
  "fulfilment-unsupported",
  "feature-unavailable",
  "reassurance",
] as const satisfies readonly PlanCaveatClass[];

/** Where a class renders on the plan review card — or that it does not. */
export type PlanCaveatPlacement =
  /** Rendered nowhere in the Demo. Kept as data, not deleted. */
  | "hidden"
  /** Inside the question-labelled reasoning expansion, alongside the reasoning. */
  | "reasoning-expansion"
  /** Resting in the Decision section, as reassurance rather than a limitation. */
  | "decision-trust-line";

export interface PlanCaveat {
  /** The class this caveat belongs to — it alone decides the presentation. */
  caveatClass: PlanCaveatClass;
  /**
   * One pre-authored seller-language sentence. Never a concatenation, and
   * never parsed: the class carries the meaning the string used to imply.
   */
  text: string;
}

/**
 * The single presentation rule per class. The card reads this, never the
 * caveat text, so a string filed under a different class moves without any
 * change to the component.
 */
export const PLAN_CAVEAT_PLACEMENT: Record<PlanCaveatClass, PlanCaveatPlacement> =
  {
    "threshold-undefined": "hidden",
    "fulfilment-unsupported": "hidden",
    "feature-unavailable": "reasoning-expansion",
    reassurance: "decision-trust-line",
  };

export function isRenderedCaveatClass(caveatClass: PlanCaveatClass): boolean {
  return PLAN_CAVEAT_PLACEMENT[caveatClass] !== "hidden";
}

/**
 * The decomposition of every workflow's known-limits blob, in the order the
 * source sentences appear. All eleven workflows are classified here — the nine
 * not yet migrated onto the plan-review spine included — so a rollout slice
 * inherits its caveats as data rather than re-deriving them.
 */
export const WORKFLOW_PLAN_CAVEATS: Record<string, readonly PlanCaveat[]> = {
  create_hero_product_1: [
    {
      caveatClass: "threshold-undefined",
      text: "Ngưỡng chính xác để phát hiện khoảng trống danh mục chưa được xác định — Juli không tự suy diễn con số này.",
    },
    {
      caveatClass: "fulfilment-unsupported",
      text: "Luồng giao hàng do TikTok quản lý cho sản phẩm mới chưa được hỗ trợ.",
    },
  ],
  optimize_product_2: [
    {
      caveatClass: "threshold-undefined",
      text: "Ngưỡng chính xác và khoảng thời gian đánh giá để đề xuất tối ưu chưa được xác định.",
    },
  ],
  // gitleaks:allow — documented mock workflow key
  replenish_inventory_3: [
    {
      caveatClass: "threshold-undefined",
      text: "Ngưỡng hết hàng chính xác, khoảng thời gian dự báo, và thoả thuận với nhà cung cấp chưa được xác định.",
    },
    {
      caveatClass: "fulfilment-unsupported",
      text: "Luồng giao hàng do TikTok quản lý cho việc nhập hàng chưa được hỗ trợ.",
    },
  ],
  clear_excess_4: [
    {
      caveatClass: "threshold-undefined",
      text: "Ngưỡng tốc độ quay vòng và tuổi hàng chính xác để kích hoạt đề xuất này chưa được xác định.",
    },
    {
      // "Won't infer the outcome" — a number Juli refuses to invent, not a
      // promise about acting. Class A, never class D.
      caveatClass: "threshold-undefined",
      text: "Juli không tự suy diễn kết quả đủ điều kiện của chương trình giảm giá nhanh.",
    },
  ],
  process_order_5: [
    {
      caveatClass: "threshold-undefined",
      text: "Ngưỡng thời gian chính xác để tạo đề xuất này chưa được xác định.",
    },
    {
      caveatClass: "fulfilment-unsupported",
      text: "Luồng giao hàng do TikTok quản lý chưa được hỗ trợ — Juli chưa thể chuẩn bị hay hoàn tất đơn hàng theo luồng đó.",
    },
  ],
  create_activity_7a: [
    {
      caveatClass: "threshold-undefined",
      text: "Ngưỡng tăng trưởng và hiệu suất để tạo đề xuất này chưa được xác định.",
    },
    {
      caveatClass: "feature-unavailable",
      text: "Juli chưa tìm được chương trình khuyến mãi hiện có theo từ khoá — chỉ làm việc với chương trình bạn đã biết.",
    },
    {
      caveatClass: "fulfilment-unsupported",
      text: "Luồng giao hàng do TikTok quản lý cho khuyến mãi chưa được hỗ trợ.",
    },
  ],
  update_activity_7c: [
    {
      caveatClass: "threshold-undefined",
      text: "Ngưỡng tăng trưởng và hiệu suất để tạo đề xuất cập nhật này chưa được xác định.",
    },
    {
      caveatClass: "feature-unavailable",
      text: "Juli chưa tìm được chương trình khuyến mãi hiện có theo từ khoá — chỉ cập nhật chương trình bạn đã biết.",
    },
    {
      caveatClass: "feature-unavailable",
      text: "Juli có thể chưa hiển thị được thông báo ngay khi chương trình khuyến mãi vừa được cập nhật.",
    },
    {
      caveatClass: "fulfilment-unsupported",
      text: "Luồng giao hàng do TikTok quản lý cho khuyến mãi chưa được hỗ trợ.",
    },
  ],
  delete_activity_7b: [
    {
      caveatClass: "threshold-undefined",
      text: "Ngưỡng tăng trưởng và hiệu suất để tạo đề xuất kết thúc này chưa được xác định.",
    },
    {
      caveatClass: "feature-unavailable",
      text: "Juli chưa tìm được chương trình khuyến mãi hiện có theo từ khoá — chỉ kết thúc chương trình bạn đã biết.",
    },
    {
      caveatClass: "fulfilment-unsupported",
      text: "Luồng giao hàng do TikTok quản lý cho khuyến mãi chưa có trong Demo.",
    },
  ],
  prevent_cancellation_8a: [
    {
      caveatClass: "threshold-undefined",
      text: "Chính sách phê duyệt hoặc từ chối tự động chính xác chưa được xác định.",
    },
    {
      caveatClass: "reassurance",
      text: "Với mọi trường hợp chưa rõ ràng, Juli không tự xử lý thay — bạn là người quyết định.",
    },
  ],
  prevent_return_8b: [
    {
      caveatClass: "threshold-undefined",
      text: "Ngưỡng và chính sách phát hiện gian lận tự động chưa được xác định.",
    },
    {
      caveatClass: "reassurance",
      text: "Juli không tự xử lý các trường hợp nghi ngờ gian lận — quyết định vẫn thuộc về bạn.",
    },
    {
      caveatClass: "fulfilment-unsupported",
      text: "Luồng giao hàng do TikTok quản lý mới chỉ được ghi nhận, Juli chưa xử lý trực tiếp.",
    },
  ],
  prevent_refund_8c: [
    {
      caveatClass: "threshold-undefined",
      text: "Ngưỡng đề xuất chính xác cho yêu cầu hoàn tiền chưa được xác định.",
    },
    {
      caveatClass: "reassurance",
      text: "Juli không tự xử lý hay chuyển tiếp yêu cầu hoàn tiền — bạn là người quyết định.",
    },
  ],
};

/** Every typed caveat for a workflow, in source order. Empty when unknown. */
export function getPlanCaveats(workflowKey: string): readonly PlanCaveat[] {
  return WORKFLOW_PLAN_CAVEATS[workflowKey] ?? [];
}

/** Filter an arbitrary caveat list by class — the card's only selector. */
export function selectPlanCaveats(
  caveats: readonly PlanCaveat[],
  caveatClass: PlanCaveatClass,
): PlanCaveat[] {
  return caveats.filter((caveat) => caveat.caveatClass === caveatClass);
}

/**
 * Classes A and B. Hidden in the Demo but kept as data: class B is the
 * fulfilment-model boundary that multi-tenant sign-in will later render as a
 * real applicability check, so it must never be deleted at the fixture.
 */
export function getHiddenCaveats(workflowKey: string): PlanCaveat[] {
  return getPlanCaveats(workflowKey).filter(
    (caveat) => !isRenderedCaveatClass(caveat.caveatClass),
  );
}

/** Class C — the gaps that render inside the reasoning expansion. */
export function getReasoningCaveats(workflowKey: string): PlanCaveat[] {
  return selectPlanCaveats(getPlanCaveats(workflowKey), "feature-unavailable");
}

/** Class D — the trust lines that render resting in the Decision section. */
export function getReassuranceCaveats(workflowKey: string): PlanCaveat[] {
  return selectPlanCaveats(getPlanCaveats(workflowKey), "reassurance");
}

/**
 * The workflows whose shipped known-limits copy promises Juli will not act
 * without the seller.
 *
 * Consumers note (#775 repeat consent): this is the class-D set derived from
 * `knownLimits` only. ADR-055 item 19 records that blocking promises live in
 * `risks` as often as in `knownLimits`, so repeat-consent eligibility is a
 * superset of this list and must not be derived from class D alone.
 */
export const REASSURANCE_CAVEAT_WORKFLOW_KEYS: readonly string[] =
  Object.keys(WORKFLOW_PLAN_CAVEATS).filter(
    (workflowKey) => getReassuranceCaveats(workflowKey).length > 0,
  );

/** Whether a workflow carries a class-D no-act promise in its known limits. */
export function hasReassuranceCaveat(workflowKey: string): boolean {
  return getReassuranceCaveats(workflowKey).length > 0;
}
