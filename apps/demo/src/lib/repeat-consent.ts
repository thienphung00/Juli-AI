/**
 * Repeat consent (ADR-055 item 19; PRD #758 slice DPR-16).
 *
 * After work finishes, Juli may ask whether it can do this kind of work
 * automatically next time. The ask is gated three ways, and every gate is a
 * refusal by default:
 *
 * | Gate | Rule |
 * |---|---|
 * | **Outcome** | Only on lifecycle `completed`. Never on `needs_input` — asking to automate a workflow that just stopped for more information is incoherent — and never mid-run. |
 * | **Frequency** | Once per **workflow kind**, not per execution. Re-asking after every approval turns a trust moment into nagging. |
 * | **Eligibility** | Never on a workflow whose shipped copy already promises Juli will not act unaided. |
 *
 * What can be granted is **pre-approval with notification**: Juli runs the work
 * and tells the seller it ran. {@link REPEAT_CONSENT_MODES} has exactly one
 * member, so there is no representable silent-automation state.
 *
 * ## Why eligibility is not derived from the class-D caveat set
 *
 * `plan-caveats.ts` class D (`reassurance`) is derived from `knownLimits`
 * alone. ADR-055 item 19 records that blocking promises live in `risks` just as
 * often, and the two sets genuinely disagree:
 *
 * - `prevent_refund_8c` **is** class D yet is **eligible** — its class-D line is
 *   about not forwarding a refund request unaided today, not a standing promise
 *   against pre-approved runs.
 * - `clear_excess_4`, `create_activity_7a` and `replenish_inventory_3` are
 *   **excluded** without being class D — their blocking promises sit in `risks`
 *   rather than in `knownLimits`.
 *
 * Deriving from class D would therefore both wrongly exclude one workflow and
 * wrongly include three. The table below is transcribed from the ADR and is the
 * single source of truth. Cross-referencing class D is a sanity check only.
 *
 * **Widening eligibility is not a prompt edit.** Flipping an entry to `true`
 * requires amending the shipped class-D / `risks` copy first, deliberately — the
 * prompt must never quietly contradict a promise the seller has already read.
 */

import type { ExecutionLifecycleStatus, ExecutionRecord } from "@juli/contracts";

/**
 * The only thing a seller can grant: Juli runs the work and tells them it ran.
 * A one-member union by design — a second mode would be the silent-automation
 * path this slice exists to forbid.
 */
export const REPEAT_CONSENT_MODES = ["pre_approved_with_notification"] as const;

export type RepeatConsentMode = (typeof REPEAT_CONSENT_MODES)[number];

export const REPEAT_CONSENT_GRANTED_MODE: RepeatConsentMode =
  "pre_approved_with_notification";

/** A standing permission is either live or withdrawn. Nothing in between. */
export type RepeatConsentStatus = "granted" | "withdrawn";

export interface RepeatConsentGrant {
  /** The workflow **kind** the permission covers — never one execution. */
  workflowKey: string;
  /** Always {@link REPEAT_CONSENT_GRANTED_MODE}. */
  mode: RepeatConsentMode;
  status: RepeatConsentStatus;
  grantedAt: string;
  /** Set the moment the seller withdraws; `null` while the grant is live. */
  withdrawnAt: string | null;
}

export type RepeatConsentGrants = Record<string, RepeatConsentGrant>;

/**
 * Why a workflow is excluded, kept next to the flag so the reason travels with
 * the decision. Excluded entries carry the promise that blocks them.
 */
interface RepeatConsentRule {
  eligible: boolean;
  /** The shipped promise that bars the ask. Empty when the workflow is eligible. */
  note: string;
}

const REPEAT_CONSENT_RULES: Record<string, RepeatConsentRule> = {
  create_hero_product_1: {
    eligible: false,
    // Not a copy promise: the MVP upload exception requires seller-supplied
    // photos, so an unattended run has nothing to upload.
    note: "Cần ảnh do shop cung cấp — không thể chạy khi thiếu ảnh.",
  },
  optimize_product_2: { eligible: true, note: "" },
  // gitleaks:allow — documented mock workflow key
  replenish_inventory_3: {
    eligible: false,
    note: "cần xác nhận số lượng nhận hàng thực tế",
  },
  clear_excess_4: {
    eligible: false,
    note: "không thể hoàn tác — chỉ thực hiện sau khi có xác nhận thực tế",
  },
  process_order_5: { eligible: true, note: "" },
  create_activity_7a: {
    eligible: false,
    note: "mọi thay đổi cần shop xác nhận trước khi gửi",
  },
  // "không tự gửi lại" bars auto-retry after a rejection, not pre-approval of
  // the initial run — so this one stays eligible.
  update_activity_7c: { eligible: true, note: "" },
  delete_activity_7b: { eligible: true, note: "" },
  prevent_cancellation_8a: {
    eligible: false,
    note: "cần shop tự quyết định, Juli không tự động xử lý thay",
  },
  prevent_return_8b: {
    eligible: false,
    note: "không tự động nhập lại kho khi chưa xác minh",
  },
  prevent_refund_8c: { eligible: true, note: "" },
};

/**
 * The eligibility table, flattened. Every shipped workflow appears exactly
 * once; a workflow absent from this table is not eligible.
 */
export const REPEAT_CONSENT_ELIGIBILITY: Record<string, boolean> =
  Object.fromEntries(
    Object.entries(REPEAT_CONSENT_RULES).map(([workflowKey, rule]) => [
      workflowKey,
      rule.eligible,
    ]),
  );

export const REPEAT_CONSENT_ELIGIBLE_WORKFLOW_KEYS: readonly string[] =
  Object.keys(REPEAT_CONSENT_ELIGIBILITY).filter(
    (workflowKey) => REPEAT_CONSENT_ELIGIBILITY[workflowKey],
  );

export const REPEAT_CONSENT_EXCLUDED_WORKFLOW_KEYS: readonly string[] =
  Object.keys(REPEAT_CONSENT_ELIGIBILITY).filter(
    (workflowKey) => !REPEAT_CONSENT_ELIGIBILITY[workflowKey],
  );

/** ELIGIBILITY gate. Unknown workflows are denied, never assumed eligible. */
export function isRepeatConsentEligible(workflowKey: string): boolean {
  return REPEAT_CONSENT_ELIGIBILITY[workflowKey] === true;
}

/** The shipped promise that bars an excluded workflow. Empty when eligible. */
export function getRepeatConsentExclusionNote(workflowKey: string): string {
  return REPEAT_CONSENT_RULES[workflowKey]?.eligible === false
    ? REPEAT_CONSENT_RULES[workflowKey].note
    : "";
}

export interface RepeatConsentGateInput {
  workflowKey: string;
  lifecycleStatus: ExecutionLifecycleStatus;
  /** Workflow kinds the seller has already answered for, granted or not. */
  promptedWorkflowKeys: readonly string[];
  grants: Readonly<RepeatConsentGrants>;
}

/**
 * All three gates, in one refusal-by-default derivation. The UI never
 * re-decides any part of this.
 */
export function shouldOfferRepeatConsent(
  input: RepeatConsentGateInput,
): boolean {
  // OUTCOME — finished work only.
  if (input.lifecycleStatus !== "completed") {
    return false;
  }

  // ELIGIBILITY — never contradict a shipped promise.
  if (!isRepeatConsentEligible(input.workflowKey)) {
    return false;
  }

  // FREQUENCY — once per workflow kind, however many executions there are.
  if (input.promptedWorkflowKeys.includes(input.workflowKey)) {
    return false;
  }

  // A kind that already carries a grant record — live or withdrawn — has been
  // asked. Withdrawal never re-opens the ask.
  if (input.grants[input.workflowKey]) {
    return false;
  }

  return true;
}

export function createRepeatConsentGrant(
  workflowKey: string,
  grantedAt: string,
): RepeatConsentGrant {
  return {
    workflowKey,
    mode: REPEAT_CONSENT_GRANTED_MODE,
    status: "granted",
    grantedAt,
    withdrawnAt: null,
  };
}

/**
 * Withdrawal — immediate, and never gated on a further approval. Returns a new
 * grant record rather than deleting it, so the withdrawn state can be shown
 * back to the seller instead of silently vanishing.
 */
export function withdrawRepeatConsentGrant(
  grant: RepeatConsentGrant,
  withdrawnAt: string,
): RepeatConsentGrant {
  return { ...grant, status: "withdrawn", withdrawnAt };
}

/** Which consent surface, if any, one execution card should carry. */
export type RepeatConsentSurface = "prompt" | "granted" | "withdrawn";

export interface RepeatConsentSurfaceInput {
  /** Execution records in display order. */
  records: readonly ExecutionRecord[];
  promptedWorkflowKeys: readonly string[];
  grants: Readonly<RepeatConsentGrants>;
}

/**
 * Maps executionId to the consent surface that execution owns.
 *
 * This is where the FREQUENCY gate is enforced across a list: the first
 * completed, eligible execution of a kind owns the surface for that kind, and
 * every later execution of the same kind carries nothing. A seller who approves
 * the same workflow ten times sees one ask, not ten.
 */
export function selectRepeatConsentSurfaces(
  input: RepeatConsentSurfaceInput,
): Record<string, RepeatConsentSurface> {
  const surfaces: Record<string, RepeatConsentSurface> = {};
  const claimedKinds = new Set<string>();

  for (const record of input.records) {
    const workflowKey = record.workflowKey;

    if (claimedKinds.has(workflowKey)) {
      continue;
    }

    // OUTCOME and ELIGIBILITY apply to the granted and withdrawn restatements
    // too — a stopped run is not the place to talk about standing permissions.
    if (record.lifecycleStatus !== "completed") {
      continue;
    }
    if (!isRepeatConsentEligible(workflowKey)) {
      continue;
    }

    const grant = input.grants[workflowKey];

    if (grant) {
      surfaces[record.executionId] = grant.status;
      claimedKinds.add(workflowKey);
      continue;
    }

    if (
      shouldOfferRepeatConsent({
        workflowKey,
        lifecycleStatus: record.lifecycleStatus,
        promptedWorkflowKeys: input.promptedWorkflowKeys,
        grants: input.grants,
      })
    ) {
      surfaces[record.executionId] = "prompt";
    }

    // Declined kinds claim the slot too, so nothing else re-asks for them.
    claimedKinds.add(workflowKey);
  }

  return surfaces;
}

/**
 * Every seller-facing string for the repeat-consent surface. Plain Vietnamese,
 * no system vocabulary, and the notification promise is stated on the face of
 * the granted state rather than buried in a settings screen.
 */
export const REPEAT_CONSENT_COPY = {
  promptTitle: "Lần sau Juli tự làm việc này nhé?",
  promptBody:
    "Việc vừa rồi đã xong. Nếu bạn đồng ý, lần sau gặp lại đúng việc này Juli sẽ tự làm và báo lại cho bạn ngay.",
  grantLabel: "Đồng ý, và báo cho tôi mỗi lần",
  declineLabel: "Không, cứ hỏi tôi trước",

  grantedTitle: "Bạn đã cho phép Juli tự làm việc này",
  grantedTerms: [
    "Lần sau gặp lại đúng việc này, Juli tự làm mà không cần hỏi bạn trước.",
    "Xong mỗi lần, Juli đều báo lại cho bạn — không có lần nào Juli làm mà bạn không biết.",
    "Chỉ áp dụng cho đúng loại việc này, không áp dụng cho việc khác.",
    "Bạn thu hồi được bất cứ lúc nào, và có hiệu lực ngay.",
  ],
  /** The notification line, also present in `grantedTerms`. */
  notificationTerm:
    "Xong mỗi lần, Juli đều báo lại cho bạn — không có lần nào Juli làm mà bạn không biết.",
  withdrawLabel: "Thu hồi quyền này",

  withdrawnNotice:
    "Bạn đã thu hồi quyền tự làm việc này. Từ giờ Juli sẽ hỏi bạn trước khi làm.",
} as const;
