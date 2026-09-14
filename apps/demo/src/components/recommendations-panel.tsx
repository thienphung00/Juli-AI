"use client";

import { RecommendationCard } from "@juli/ui";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  buildRecommendationDetailHref,
  recommendationFixtures,
} from "../lib/recommendations";
import { readReplayDecision } from "../lib/replay-decision";
import { APPROVABLE_WORKFLOW_KEYS, OPTIMIZE_PRODUCT_WORKFLOW_KEY } from "../lib/reviews";
import { REPLAY_SCENARIO_RUN_ID } from "../lib/run-surface/replay-scenario";
import { useDemoState } from "./demo-state";

const APPROVE_DISABLED_REASON =
  "Phê duyệt: luồng xem trước và điền thông tin trước khi thực thi chưa có trong Demo này — sẽ ra mắt ở bản cập nhật tiếp theo.";

interface RecommendationsPanelProps {
  initialLoadState?: "ready" | "error";
  panelId: string;
}

export function RecommendationsPanel({
  initialLoadState = "ready",
  panelId,
}: RecommendationsPanelProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const highlightKey = searchParams.get("highlight");
  const {
    mutableState,
    setRecommendationContext,
    updateMutableState,
  } = useDemoState();
  const highlightedCardRef = useRef<HTMLElement | null>(null);
  const recommendationsPanelRef = useRef<HTMLDivElement | null>(null);
  const detailRef = useRef<HTMLElement | null>(null);
  const splitRef = useRef<HTMLDivElement | null>(null);
  const [loadState, setLoadState] = useState(initialLoadState);
  const [statusMessage, setStatusMessage] = useState("");
  // Issue #1916 (v3 draft): "Xem thêm" opens this recommendation's detail
  // BESIDE the list — the list narrows, the detail takes the remainder,
  // never an overlay or a modal (owner direction, stated twice).
  const [detailKey, setDetailKey] = useState<string | null>(null);

  // Issue #1836 / ADR-084 decision 6: a decided replay run consumes its
  // card the same way an approved or rejected one does, just via a
  // different store (`sessionStorage`, since the replay path persists
  // nothing -- ADR-094 decision 1). `null` on first render (server and
  // client agree -- `window` is unavailable during SSR) and resolved in an
  // effect, deferred via `setTimeout(0)` rather than calling the setter
  // synchronously in the effect body -- the same pattern `demo-landing.tsx`
  // and `impact-block.tsx` already use for their own browser-storage reads
  // (`react-hooks/set-state-in-effect`). Depends on `mutableState` so
  // "Làm mới Demo" (which replaces that reference via `resetMockState`)
  // re-reads sessionStorage and picks up the now-cleared record.
  const [replayDecidedWorkflowKey, setReplayDecidedWorkflowKey] = useState<
    string | null
  >(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const decision = readReplayDecision();
      setReplayDecidedWorkflowKey(
        decision?.runId === REPLAY_SCENARIO_RUN_ID
          ? OPTIMIZE_PRODUCT_WORKFLOW_KEY
          : null,
      );
    }, 0);

    return () => window.clearTimeout(timer);
  }, [mutableState]);

  const visibleFixtures = useMemo(
    () =>
      recommendationFixtures.filter(
        (fixture) =>
          !mutableState.rejectedRecommendationIds.includes(
            fixture.workflowKey,
          ) &&
          !mutableState.approvedRecommendationIds.includes(
            fixture.workflowKey,
          ) &&
          fixture.workflowKey !== replayDecidedWorkflowKey,
      ),
    [
      mutableState.approvedRecommendationIds,
      mutableState.rejectedRecommendationIds,
      replayDecidedWorkflowKey,
    ],
  );

  const activeFixture =
    visibleFixtures.find((fixture) => fixture.workflowKey === highlightKey) ??
    visibleFixtures[0] ??
    null;

  const detailFixture =
    visibleFixtures.find((fixture) => fixture.workflowKey === detailKey) ??
    null;

  useEffect(() => {
    setRecommendationContext(
      activeFixture
        ? {
            evidence: activeFixture.evidence,
            risks: activeFixture.risks,
            title: activeFixture.title,
            workflowKey: activeFixture.workflowKey,
          }
        : null,
    );

    return () => setRecommendationContext(null);
  }, [activeFixture, setRecommendationContext]);

  useEffect(() => {
    if (!highlightKey) {
      return;
    }

    const node = highlightedCardRef.current;

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
  }, [highlightKey]);

  // Focus travels with the detail: into the region when it opens (card →
  // detail), back to the card when "Quay lại" restores the grid.
  useEffect(() => {
    if (detailKey) {
      detailRef.current?.focus();
    }
  }, [detailKey]);

  const focusCard = (workflowKey: string) => {
    window.setTimeout(() => {
      splitRef.current
        ?.querySelector<HTMLElement>(
          `article[data-workflow-key="${workflowKey}"]`,
        )
        ?.focus();
    }, 0);
  };

  const handleCloseDetail = () => {
    const closingKey = detailKey;
    setDetailKey(null);
    if (closingKey) {
      focusCard(closingKey);
    }
  };

  const handleReject = (workflowKey: string) => {
    const rejectedFixture = recommendationFixtures.find(
      (fixture) => fixture.workflowKey === workflowKey,
    );

    if (detailKey === workflowKey) {
      setDetailKey(null);
    }

    updateMutableState((current) => ({
      ...current,
      rejectedRecommendationIds: [
        ...current.rejectedRecommendationIds,
        workflowKey,
      ],
    }));
    setStatusMessage(
      rejectedFixture
        ? `Đã từ chối đề xuất ${rejectedFixture.title}.`
        : "Đã từ chối đề xuất.",
    );
    window.setTimeout(() => recommendationsPanelRef.current?.focus(), 0);
  };

  const handleApprove = (workflowKey: string) => {
    router.push(`/decisions/recommendations/${workflowKey}`);
  };

  return (
    <div
      ref={recommendationsPanelRef}
      aria-label="Đề xuất"
      id={panelId}
      tabIndex={-1}
    >
      <p aria-live="polite" className="demo-decisions__status" role="status">
        {statusMessage}
      </p>
      {loadState === "error" ? (
        <section
          aria-label="Lỗi tải đề xuất"
          className="demo-decisions__empty"
          role="alert"
        >
          <p className="demo-kicker">Chưa thể tải nội dung</p>
          <h2>Không thể tải đề xuất mẫu</h2>
          <p>Dữ liệu mẫu chưa sẵn sàng. Bạn có thể thử lại ngay.</p>
          <button
            className="demo-decisions__retry"
            onClick={() => setLoadState("ready")}
            type="button"
          >
            Thử lại
          </button>
        </section>
      ) : visibleFixtures.length === 0 ? (
        <section
          aria-label="Đề xuất"
          className="demo-decisions__empty"
          role="status"
        >
          <p className="demo-kicker">Chưa có dữ liệu</p>
          <h2>Không có đề xuất nào cần xem xét</h2>
          <p>
            Hiện chưa có tín hiệu nào cần bạn xem xét. Mở Phân tích để hiểu
            thêm về shop, hoặc dùng Làm mới Demo để xem lại toàn bộ đề xuất
            mẫu.
          </p>
          <Link className="demo-placeholder__recovery" href="/analytics">
            Mở Phân tích
          </Link>
        </section>
      ) : (
        <div
          ref={splitRef}
          className="demo-decisions__split"
          data-detail-open={detailFixture ? "true" : "false"}
          data-testid="decisions-split"
        >
          <ul className="demo-decisions__list">
            {visibleFixtures.map((fixture) => {
              const isHighlighted = fixture.workflowKey === highlightKey;
              const approveEnabled = APPROVABLE_WORKFLOW_KEYS.includes(
                fixture.workflowKey as (typeof APPROVABLE_WORKFLOW_KEYS)[number],
              );

              return (
                <li key={fixture.workflowKey}>
                  <RecommendationCard
                    ref={isHighlighted ? highlightedCardRef : undefined}
                    approveDisabledReason={
                      approveEnabled ? undefined : APPROVE_DISABLED_REASON
                    }
                    categoryLabel={fixture.title}
                    detailHref={buildRecommendationDetailHref(fixture.workflowKey)}
                    eligibility={fixture.eligibility}
                    evidence={fixture.evidence}
                    isHighlighted={isHighlighted}
                    isPriority={fixture.isPriority}
                    knownLimits={fixture.knownLimits}
                    onApprove={
                      approveEnabled
                        ? () => handleApprove(fixture.workflowKey)
                        : undefined
                    }
                    onReject={() => handleReject(fixture.workflowKey)}
                    onSeeMore={() => setDetailKey(fixture.workflowKey)}
                    previewRows={fixture.previewRows}
                    reasoning={fixture.reasoning}
                    risks={fixture.risks}
                    seeMoreOpen={fixture.workflowKey === detailKey}
                    sellerReason={fixture.sellerReason}
                    signal={fixture.signal}
                    title={fixture.subject}
                    workflowKey={fixture.workflowKey}
                  />
                </li>
              );
            })}
          </ul>
          {detailFixture ? (
            <section
              ref={detailRef}
              aria-label="Chi tiết đề xuất"
              className="demo-decisions__detail"
              tabIndex={-1}
            >
              <button
                className="demo-decisions__detail-back"
                onClick={handleCloseDetail}
                type="button"
              >
                <span aria-hidden="true">←</span> Quay lại
              </button>
              <p className="demo-kicker">{detailFixture.title}</p>
              <h2 className="demo-decisions__detail-title">
                {detailFixture.subject}
              </h2>
              <p className="demo-decisions__detail-signal">
                {detailFixture.signal}
              </p>
              <dl className="demo-decisions__detail-facts">
                <div>
                  <dt>Lý do đề xuất</dt>
                  <dd>{detailFixture.reasoning}</dd>
                </div>
                <div>
                  <dt>Bằng chứng</dt>
                  <dd>{detailFixture.evidence}</dd>
                </div>
                <div>
                  <dt>Điều kiện áp dụng</dt>
                  <dd>{detailFixture.eligibility}</dd>
                </div>
                <div>
                  <dt>Giới hạn hiện tại</dt>
                  <dd>{detailFixture.knownLimits}</dd>
                </div>
                <div>
                  <dt>Rủi ro</dt>
                  <dd>{detailFixture.risks}</dd>
                </div>
              </dl>
            </section>
          ) : null}
        </div>
      )}
    </div>
  );
}
