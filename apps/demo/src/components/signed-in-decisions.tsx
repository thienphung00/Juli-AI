"use client";

/**
 * The SIGNED-IN Decisions branch (issue #1909) — the component-level
 * anonymous/signed-in split `apps/demo/MODULE.md` deliberately deferred
 * until this slice. `RecommendationsView` (the anonymous branch) keeps
 * rendering `recommendationFixtures` unchanged and stays inside a module
 * graph that reaches no network call site (ADR-094 decision 1,
 * `src/__tests__/replay-module-graph.test.ts`); THIS module is the
 * signed-in branch's own module, following `replay-run-detail.tsx`'s
 * precedent in the opposite direction — it alone imports the authenticated
 * clients (`fetchRecommendations`, `approveDemoDecision`), and nothing on
 * the anonymous entry graph imports it.
 *
 * What it does, per the issue's vertical slice:
 *  - reads the acting shop from `lib/shop-session.ts` and SAYS so
 *    (`decisions.signed_in.acting_shop`), so a multi-shop seller always
 *    knows which shop every `X-Shop-Id` belongs to;
 *  - reads `GET /v1/demo/decisions` with the bearer token — a failure is
 *    rendered honestly (`error.decisions.load_failed`) and NEVER papered
 *    over with `recommendationFixtures` (#1320);
 *  - approve is two-step consent (#1317's pattern) and then a single
 *    `POST /v1/demo/decisions/{id}/approve`; navigation uses the `run_id`
 *    FROM THE RESPONSE, never a client-constructed id;
 *  - a 401 / 404 / 409 from approve each render their own honest
 *    Vietnamese message (dictionary.md `error.approve.*`).
 */

import type { DemoDecisionItem } from "@juli/contracts";
import { ConfirmDialog } from "@juli/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import {
  approveDemoDecision,
  fetchRecommendations,
} from "../lib/recommendations-api-client";
import { DemoDecisionApproveError } from "../lib/recommendations-api-client";
import { readActiveShop } from "../lib/shop-session";
import { ACTIONS_DESTINATION_LABEL } from "../lib/destination-copy";
import { mapDecisionEvidence } from "../lib/decision-evidence";
import { DecisionEvidenceBlock } from "./decision-evidence-block";
import { InProgressPanel } from "./in-progress-panel";

/** dictionary.md `decisions.signed_in.no_shop` */
const NO_SHOP_COPY =
  "Bạn chưa chọn shop đang thao tác. Mở Kết nối TikTok Shop để chọn shop.";

/** dictionary.md `error.decisions.load_failed` */
const LOAD_FAILED_COPY =
  "Không thể tải đề xuất cho shop của bạn. Vui lòng thử lại.";

/** dictionary.md `decisions.approve.confirm_title` / `decisions.approve.confirm_body` */
const APPROVE_CONFIRM_TITLE = "Phê duyệt đề xuất này?";
const APPROVE_CONFIRM_BODY =
  "Juli sẽ bắt đầu một luồng thực hiện thật trên shop của bạn. Bạn vẫn xem và xác nhận từng thay đổi trước khi áp dụng.";

/** dictionary.md `error.approve.session_expired` / `not_found` / `conflict` /
 *  `generic` — the three statuses the approve route actually distinguishes
 *  (plus an honest fallback), each its own sentence, none a fixture. */
function describeApproveError(error: unknown): string {
  if (error instanceof DemoDecisionApproveError) {
    if (error.status === 401) {
      return "Phiên đăng nhập của bạn không còn hiệu lực. Vui lòng đăng nhập với Google lại, rồi phê duyệt.";
    }
    if (error.status === 404) {
      return "Đề xuất này không còn tồn tại hoặc không thuộc shop bạn đang thao tác.";
    }
    if (error.status === 409) {
      return "Đề xuất này đã được xử lý, hoặc sản phẩm đang có luồng khác chạy. Hãy kiểm tra tab Đang thực hiện.";
    }
    return `Chưa thể phê duyệt đề xuất này lúc này (lỗi ${error.status}). Vui lòng thử lại.`;
  }
  // dictionary.md `error.network`
  return "Không thể kết nối. Vui lòng kiểm tra mạng và thử lại.";
}

function severityBadge(severity: string): { label: string; className: string } {
  switch (severity) {
    case "critical":
      return { label: "Khẩn cấp", className: "badge badge-danger" };
    case "high":
      return { label: "Ưu tiên cao", className: "badge badge-warning" };
    case "warning":
      return { label: "Chú ý", className: "badge badge-info" };
    default:
      return { label: "Thông tin", className: "badge badge-info" };
  }
}

/** Shown once the seller has declined at least one card this session. */
const REJECTED_COPY =
  "Đã gỡ đề xuất bạn từ chối khỏi danh sách. Lựa chọn này chưa được lưu, nên đề xuất có thể xuất hiện lại khi bạn tải lại trang.";

function visibleItems(
  items: readonly DemoDecisionItem[],
  rejected: ReadonlySet<string>,
): readonly DemoDecisionItem[] {
  return items.filter((item) => !rejected.has(item.id));
}

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: readonly DemoDecisionItem[] };

interface SignedInDecisionsProps {
  readonly token: string;
  /** Injectable for tests; default to the real authenticated clients. */
  readonly loadDecisions?: typeof fetchRecommendations;
  readonly approve?: typeof approveDemoDecision;
}

export function SignedInDecisions({
  token,
  loadDecisions = fetchRecommendations,
  approve = approveDemoDecision,
}: SignedInDecisionsProps) {
  const router = useRouter();
  const recommendationsPanelId = useId();
  const inProgressPanelId = useId();

  // Client-only surface (the page renders this branch only after resolving
  // the stored session in an effect), so the storage read in the
  // initializer never runs during SSR.
  const [activeShop] = useState(() => readActiveShop());
  const [view, setView] = useState<"recommendations" | "in-progress">(
    "recommendations",
  );
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const [pendingApproval, setPendingApproval] = useState<DemoDecisionItem | null>(null);
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);
  // "Từ chối" has no backend route yet (DEBT): the card is removed from this
  // session's list only, and the copy says so.
  const [rejectedIds, setRejectedIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const approveErrorRef = useRef<HTMLParagraphElement | null>(null);

  // The error renders above the list; the seller who just clicked Phê duyệt
  // inside a card further down must actually SEE it, not just have it
  // announced -- bring it into view and hand it focus when it appears.
  useEffect(() => {
    if (!approveError) {
      return;
    }

    const node = approveErrorRef.current;

    if (!node) {
      return;
    }

    const prefersReducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    node.scrollIntoView({
      behavior: prefersReducedMotion ? "auto" : "smooth",
      block: "center",
    });
    node.focus();
  }, [approveError]);

  useEffect(() => {
    if (!activeShop) {
      return;
    }

    let cancelled = false;

    loadDecisions({ token, shopId: activeShop.id })
      .then((items) => {
        if (!cancelled) setLoadState({ status: "ready", items });
      })
      .catch(() => {
        if (!cancelled) setLoadState({ status: "error" });
      });

    return () => {
      cancelled = true;
    };
    // activeShop is resolved once per mount; reloadKey drives the retry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, reloadKey]);

  if (!activeShop) {
    return (
      <section aria-labelledby="decisions-title" className="demo-decisions">
        <p className="demo-kicker">{ACTIONS_DESTINATION_LABEL}</p>
        <h1 className="demo-title" id="decisions-title">
          Việc cần bạn quyết định
        </h1>
        <section aria-label="Chưa chọn shop" className="demo-decisions__empty" role="status">
          <p>{NO_SHOP_COPY}</p>
          <Link className="demo-placeholder__recovery" href="/auth/connect-shop">
            Kết nối TikTok Shop
          </Link>
        </section>
      </section>
    );
  }

  const handleApproveConfirm = () => {
    if (!pendingApproval || approving) {
      return;
    }

    const card = pendingApproval;
    setApproving(true);
    setApproveError(null);

    approve(card.id, { token, shopId: activeShop.id })
      .then(({ runId }) => {
        // The server's own run_id — never a client-constructed one.
        router.push(`/decisions/in-progress/${runId}`);
      })
      .catch((error: unknown) => {
        setApproveError(describeApproveError(error));
      })
      .finally(() => {
        setApproving(false);
        setPendingApproval(null);
      });
  };

  return (
    <section aria-labelledby="decisions-title" className="demo-decisions">
      <p className="demo-kicker">{ACTIONS_DESTINATION_LABEL}</p>
      <h1 className="demo-title" id="decisions-title">
        Việc cần bạn quyết định
      </h1>
      <p className="demo-decisions__acting-shop">
        Bạn đang thao tác trên: <strong>{activeShop.name}</strong>
      </p>

      <div aria-label="Loại quyết định" className="demo-decisions__tabs" role="group">
        <button
          aria-controls={recommendationsPanelId}
          aria-pressed={view === "recommendations"}
          className="demo-decisions__tab"
          onClick={() => setView("recommendations")}
          type="button"
        >
          Đề xuất
        </button>
        <button
          aria-controls={inProgressPanelId}
          aria-pressed={view === "in-progress"}
          className="demo-decisions__tab"
          onClick={() => setView("in-progress")}
          type="button"
        >
          Đang thực hiện
        </button>
      </div>

      {approveError && (
        <p
          ref={approveErrorRef}
          className="signed-in-decision__approve-error"
          role="alert"
          tabIndex={-1}
        >
          {approveError}
        </p>
      )}

      <div hidden={view !== "recommendations"}>
        <div aria-label="Đề xuất" id={recommendationsPanelId}>
          {loadState.status === "loading" && (
            <p role="status" aria-live="polite">
              Đang tải đề xuất cho shop của bạn…
            </p>
          )}

          {loadState.status === "error" && (
            <section aria-label="Lỗi tải đề xuất" className="demo-decisions__empty" role="alert">
              <p className="demo-kicker">Chưa thể tải nội dung</p>
              <p>{LOAD_FAILED_COPY}</p>
              <button
                className="demo-decisions__retry"
                onClick={() => {
                  setLoadState({ status: "loading" });
                  setReloadKey((key) => key + 1);
                }}
                type="button"
              >
                Thử lại
              </button>
            </section>
          )}

          {rejectedIds.size > 0 && (
            <p className="decision-card__rejected-note" role="status">
              {REJECTED_COPY}
            </p>
          )}

          {loadState.status === "ready" && visibleItems(loadState.items, rejectedIds).length === 0 && rejectedIds.size === 0 && (
            <section aria-label="Đề xuất" className="demo-decisions__empty" role="status">
              <p className="demo-kicker">Chưa có dữ liệu</p>
              {/* dictionary.md `empty.decisions.waiting_data` */}
              <p>
                Juli đang thu thập dữ liệu shop của bạn. Đề xuất đầu tiên sẽ
                xuất hiện trong vòng 24 giờ.
              </p>
            </section>
          )}

          {loadState.status === "ready" && visibleItems(loadState.items, rejectedIds).length > 0 && (
            <ul className="demo-decisions__list">
              {visibleItems(loadState.items, rejectedIds).map((item) => (
                <li key={item.id}>
                  <SignedInDecisionCard
                    item={item}
                    onApprove={() => {
                      setApproveError(null);
                      setPendingApproval(item);
                    }}
                    onReject={() => {
                      setRejectedIds((ids) => new Set(ids).add(item.id));
                    }}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div hidden={view !== "in-progress"}>
        <InProgressPanel
          active={view === "in-progress"}
          panelId={inProgressPanelId}
          shopId={activeShop.id}
          token={token}
        />
      </div>

      <ConfirmDialog
        confirmLabel="Phê duyệt"
        description={APPROVE_CONFIRM_BODY}
        onCancel={() => setPendingApproval(null)}
        onConfirm={handleApproveConfirm}
        onOpenChange={(open) => {
          if (!open) setPendingApproval(null);
        }}
        open={pendingApproval !== null}
        title={APPROVE_CONFIRM_TITLE}
      />
    </section>
  );
}

function SignedInDecisionCard({
  item,
  onApprove,
  onReject,
}: {
  readonly item: DemoDecisionItem;
  readonly onApprove: () => void;
  readonly onReject: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const severity = severityBadge(item.severity);
  const reasoning = item.recommendation.reasoning ?? null;
  const evidence = mapDecisionEvidence(item);
  const reasoningId = `reasoning-${item.id}`;
  const hasReasoning = Boolean(
    reasoning?.why ||
      item.recommendation.rationale ||
      (reasoning && reasoning.next_steps.length > 0),
  );

  return (
    <article
      className="card decision-card"
      data-decision-id={item.id}
      data-testid="recommendation-card"
    >
      <div className="decision-card__head">
        <p className="decision-card__kicker">
          <svg
            aria-hidden="true"
            fill="none"
            height="16"
            stroke="currentColor"
            strokeWidth="2"
            viewBox="0 0 24 24"
            width="16"
          >
            <path
              d="M12 3v4M12 17v4M5 12H3M21 12h-2M6.5 6.5l1.5 1.5M16 16l1.5 1.5M17.5 6.5L16 8M8 16l-1.5 1.5"
              strokeLinecap="round"
            />
          </svg>
          Đề xuất
        </p>
        <span className={severity.className}>{severity.label}</span>
      </div>
      <h2 className="decision-card__headline">{item.title}</h2>
      <p className="decision-card__description">{item.description}</p>
      {reasoning?.expected_impact && (
        <p className="decision-card__impact">
          Tác động dự kiến: <strong>{reasoning.expected_impact}</strong>
        </p>
      )}
      {evidence && <DecisionEvidenceBlock evidence={evidence} />}
      {expanded && hasReasoning && (
        <div className="decision-card__reasoning" id={reasoningId}>
          <strong>Lý do đề xuất</strong>
          {reasoning?.why && <p>{reasoning.why}</p>}
          {item.recommendation.rationale && <p>{item.recommendation.rationale}</p>}
          {reasoning && reasoning.next_steps.length > 0 && (
            <>
              <p className="decision-card__label" id={`steps-${item.id}`}>
                Các bước tiếp theo
              </p>
              <ol aria-labelledby={`steps-${item.id}`} className="decision-card__steps">
                {reasoning.next_steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            </>
          )}
        </div>
      )}
      {!item.is_executable && (
        <p className="signed-in-decision__manual-note">
          Đề xuất này cần bạn thực hiện thủ công — Juli chưa tự thực thi được.
        </p>
      )}
      <div className="decision-card__actions">
        {item.is_executable && (
          <button className="btn-primary" onClick={onApprove} type="button">
            Phê duyệt
          </button>
        )}
        <button className="btn-secondary" onClick={onReject} type="button">
          Từ chối
        </button>
        {hasReasoning && (
          <button
            aria-controls={expanded ? reasoningId : undefined}
            aria-expanded={expanded}
            className="btn-secondary decision-card__expand"
            onClick={() => setExpanded((value) => !value)}
            type="button"
          >
            {expanded ? "Thu gọn" : "Mở rộng"}
          </button>
        )}
      </div>
    </article>
  );
}
