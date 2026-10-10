"use client";

import { ConfirmDialog } from "@juli/ui";
import { useEffect, useState } from "react";

import { cardView, gmvMonthText, type CardView } from "../../lib/quyet-dinh/card-model";
import {
  BANDS_MISSING_BODY,
  BANDS_MISSING_PROMPT,
  LEVER_LABELS,
  RULE_BASED_ESTIMATE,
  bandMetricLabel,
  setByLabel,
} from "../../lib/quyet-dinh/copy";
import { analysisHrefForDecision, cardMetric } from "../../lib/phan-tich/cards";
import { batchCards, type DecisionGroup } from "../../lib/quyet-dinh/grouping";
import type { CardStatus, P10DecisionItem } from "../../lib/quyet-dinh/p10-types";
import type { ReasonChoice } from "../../lib/quyet-dinh/reasons";
import { bandsAreSet, setBands, type ShopRules } from "../../lib/quyet-dinh/types";
import { num } from "../../lib/vn-format";
import { REJECT_DIALOG_BODY, ReasonDialog } from "./reason-dialog";
import { RecommendationCard } from "./recommendation-card";
import { useNarrow } from "./use-narrow";

/**
 * Đề xuất (ADR-109 Amendment 1; `Main.dc.html`, `Mobile.dc.html`,
 * `Levers.dc.html`). Above the cards (P8, kept): the seller's stability
 * bands and rules (d.11/d.12) and, per stream × stage group, "Duyệt N thẻ".
 * The cards themselves are the artboards' card.
 */

export interface DeXuatPanelProps {
  readonly groups: readonly DecisionGroup[];
  readonly rules: ShopRules | null;
  readonly rulesStatus: "loading" | "error" | "ready";
  /** Local status overrides (approved → running, rejected) by card id. */
  readonly statusOverrides: Readonly<Record<string, CardStatus>>;
  /** Run created by this visit's approve, by card id. */
  readonly runByCard: Readonly<Record<string, string>>;
  readonly busy: boolean;
  readonly progress: string | null;
  readonly cardErrors: Readonly<Record<string, string>>;
  readonly onApprove: (cardIds: readonly string[]) => void;
  readonly onReject: (cardId: string, choice: ReasonChoice) => Promise<void>;
  readonly onOpenRules: () => void;
  readonly onOpenRun: (runId: string | null) => void;
  readonly progressHref: (runId: string | null) => string;
  /** Phân tích's "Xem đề xuất ›": the card to scroll to and outline for 3 s. */
  readonly focusCard?: string | null;
  /** Phân tích's "Xem N đề xuất ›": the metric (ctr / ctor / aov) whose group to scroll to. */
  readonly focusMetric?: string | null;
}

/** How long an arriving card / group stays outlined (PtFlow: "viền hồng 3 giây"). */
export const FOCUS_MS = 3000;

function groupMetric(group: DecisionGroup): string | null {
  const first = group.cards[0]?.item;
  return first ? cardMetric(first) : null;
}

export function DeXuatPanel({
  groups,
  rules,
  rulesStatus,
  statusOverrides,
  runByCard,
  busy,
  progress,
  cardErrors,
  onApprove,
  onReject,
  onOpenRules,
  onOpenRun,
  progressHref,
  focusCard = null,
  focusMetric = null,
}: DeXuatPanelProps) {
  const narrow = useNarrow();
  const focusGroupKey = focusMetric ? (groups.find((group) => groupMetric(group) === focusMetric)?.key ?? null) : null;
  const focusTarget = focusCard ? `card:${focusCard}` : focusGroupKey ? `group:${focusGroupKey}` : null;
  const [highlight, setHighlight] = useState<string | null>(null);
  useEffect(() => {
    if (!focusTarget) return;
    const attribute = focusTarget.startsWith("card:") ? "data-decision-id" : "data-group-key";
    const value = focusTarget.slice(focusTarget.indexOf(":") + 1);
    const element = [...document.querySelectorAll(`[${attribute}]`)].find((el) => el.getAttribute(attribute) === value);
    if (!element) return;
    element.scrollIntoView?.({ block: "center", behavior: "smooth" });
    const start = window.setTimeout(() => setHighlight(focusTarget), 0);
    const timer = window.setTimeout(() => setHighlight(null), FOCUS_MS);
    return () => {
      window.clearTimeout(start);
      window.clearTimeout(timer);
    };
  }, [focusTarget]);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());
  const [pendingBatch, setPendingBatch] = useState<readonly string[] | null>(null);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [rejectBusy, setRejectBusy] = useState(false);
  const [rejectError, setRejectError] = useState<string | null>(null);
  const [rejectReasons, setRejectReasons] = useState<Readonly<Record<string, string>>>({});
  const bandsSet = bandsAreSet(rules);

  const statusOf = (card: CardView): CardStatus => statusOverrides[card.id] ?? card.status;
  const blockReason = !bandsSet ? (rulesStatus === "loading" ? "Đang tải quy tắc của shop…" : BANDS_MISSING_PROMPT) : null;

  return (
    <div className="qv-dx">
      <div className="qv-dx__rules">
        <StabilityCard onOpenRules={onOpenRules} rules={rules} rulesStatus={rulesStatus} />
        <RulesChips onOpenRules={onOpenRules} rules={rules} />
      </div>

      {groups.map((group) => {
        const views = group.cards.map((card) => cardView(card.item as P10DecisionItem));
        const excluded = new Set(views.filter((view) => statusOf(view) !== "pending").map((view) => view.id));
        const runnable = batchCards(group, excluded);
        const headingId = `qd-group-${group.key.replace(/[^a-z0-9]/gi, "-")}`;
        const gmv = gmvMonthText(group.gmvPerMonth);
        // P14-E: content cards change nothing on the listing, so the stability bands
        // do not gate them, and each one is filmed separately (no batch approve).
        const cardBlock = group.content ? null : blockReason;
        const groupBlock =
          blockReason ?? (runnable.length === 0 ? "Không còn thẻ nào Juli tự thực hiện được trong nhóm này." : null);
        return (
          <section
            aria-labelledby={headingId}
            className={`qv-group${highlight === `group:${group.key}` ? " qv-group--focus" : ""}`}
            data-group-key={group.key}
            data-testid="decision-group"
            key={group.key}
          >
            <div className="qv-group__head">
              <div className="qv-group__titles">
                <h2 className="qv-group__title" id={headingId}>
                  {group.title}
                </h2>
                {gmv ? (
                  <span className="qv-group__sub" data-testid="group-gmv">
                    GMV dự kiến {gmv} · {RULE_BASED_ESTIMATE}
                  </span>
                ) : null}
              </div>
              {group.content ? null : (
              <div className="qv-group__actions">
                <button
                  aria-describedby={groupBlock ? `${headingId}-block` : undefined}
                  className="qv-btn qv-btn--primary"
                  disabled={busy || groupBlock !== null}
                  onClick={() => setPendingBatch(runnable.map((card) => card.id))}
                  type="button"
                >
                  Duyệt {runnable.length} thẻ
                </button>
                <button className="qv-btn qv-btn--secondary" onClick={onOpenRules} type="button">
                  Sửa
                </button>
              </div>
              )}
              {groupBlock && !group.content ? (
                <p className="qv-group__block" id={`${headingId}-block`}>
                  {groupBlock}
                </p>
              ) : null}
            </div>
            <ul className="qv-cards">
              {views.map((view) => {
                const status = statusOf(view);
                const runId = runByCard[view.id] ?? null;
                return (
                  <li key={view.id}>
                    <RecommendationCard
                      analysisHref={analysisHrefForDecision(group.cards.find((c) => c.id === view.id)?.item ?? group.cards[0].item)}
                      blockedReason={cardBlock}
                      focused={highlight === `card:${view.id}`}
                      rejectReason={rejectReasons[view.id] ?? null}
                      busy={busy}
                      card={view}
                      error={cardErrors[view.id] ?? null}
                      expanded={expanded.has(view.id)}
                      narrow={narrow}
                      onApprove={() => onApprove([view.id])}
                      onOpenProgress={(event) => {
                        event.preventDefault();
                        onOpenRun(runId);
                      }}
                      onReject={() => {
                        setRejectError(null);
                        setRejecting(view.id);
                      }}
                      onToggle={() =>
                        setExpanded((set) => {
                          const next = new Set(set);
                          if (next.has(view.id)) next.delete(view.id);
                          else next.add(view.id);
                          return next;
                        })
                      }
                      progressHref={progressHref(runId)}
                      status={status}
                    />
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
      {progress ? (
        <p className="qv-status-line" role="status">
          {progress}
        </p>
      ) : null}

      <ReasonDialog
        body={REJECT_DIALOG_BODY}
        busy={rejectBusy}
        error={rejectError}
        mode="reject"
        onCancel={() => setRejecting(null)}
        onSubmit={(choice) => {
          if (!rejecting) return;
          setRejectBusy(true);
          setRejectError(null);
          const cardId = rejecting;
          onReject(cardId, choice)
            .then(() => {
              setRejectReasons((map) => ({ ...map, [cardId]: choice.reason_code }));
              setRejecting(null);
            })
            .catch((error: unknown) =>
              setRejectError(error instanceof Error && error.message ? error.message : "Chưa từ chối được. Vui lòng thử lại."),
            )
            .finally(() => setRejectBusy(false));
        }}
        open={rejecting !== null}
      />

      <ConfirmDialog
        confirmLabel="Duyệt"
        description={
          pendingBatch
            ? `Juli tạo ${pendingBatch.length} lượt chạy và thực hiện lần lượt từng thẻ, không bao giờ hai thay đổi cùng lúc trên một sản phẩm. Mỗi lượt vẫn dừng lại để bạn xác nhận trước khi ghi lên TikTok Shop.`
            : ""
        }
        onCancel={() => setPendingBatch(null)}
        onConfirm={() => {
          if (pendingBatch) onApprove(pendingBatch);
          setPendingBatch(null);
        }}
        onOpenChange={(open) => {
          if (!open) setPendingBatch(null);
        }}
        open={pendingBatch !== null}
        title={pendingBatch ? `Duyệt ${pendingBatch.length} thẻ?` : ""}
      />
    </div>
  );
}

function StabilityCard({
  rules,
  rulesStatus,
  onOpenRules,
}: {
  readonly rules: ShopRules | null;
  readonly rulesStatus: "loading" | "error" | "ready";
  readonly onOpenRules: () => void;
}) {
  const bands = setBands(rules);
  return (
    <section aria-labelledby="qd-stability" className="qv-side" data-testid="stability-card">
      <h2 className="qv-side__title" id="qd-stability">
        Giữ ổn định
      </h2>
      {rulesStatus === "loading" ? (
        <p className="qv-side__text">Đang tải quy tắc…</p>
      ) : rulesStatus === "error" ? (
        <p className="qv-side__text" role="alert">
          Không tải được quy tắc của shop. Juli chưa chạy thẻ nào cho tới khi đọc được ngưỡng.
        </p>
      ) : bands.length === 0 ? (
        <>
          <p className="qv-side__text" role="status">
            <strong>{BANDS_MISSING_PROMPT}</strong>
          </p>
          <p className="qv-side__text">{BANDS_MISSING_BODY}</p>
          <div className="qv-side__actions">
            <button className="qv-btn qv-btn--primary" onClick={onOpenRules} type="button">
              Đặt ngưỡng
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="qv-side__text">Ngày thứ 7, chỉ số nào lệch quá ngưỡng thì Juli hỏi bạn có hoàn tác không.</p>
          <ul className="qv-side__chips">
            {bands.map((band) => (
              <li className="qv-side__chip" key={band.metric} title={setByLabel(band.setBy)}>
                <span aria-hidden="true">🔒</span> {bandMetricLabel(band.metric)} · ±{num(band.band, band.band % 1 ? 1 : 0)} %
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

interface RuleChip {
  readonly key: string;
  readonly text: string;
  readonly setBy: string | null;
}

export function ruleChips(rules: ShopRules | null): RuleChip[] {
  if (!rules) return [];
  const chips: RuleChip[] = [];
  if (rules.min_margin_pct?.set_by) {
    chips.push({
      key: "min_margin_pct",
      text: `Biên lợi nhuận ≥ ${num(Number(rules.min_margin_pct.value), 0)} %`,
      setBy: rules.min_margin_pct.set_by,
    });
  }
  const discounts = Object.values(rules.max_discount_pct).filter((item) => item.set_by);
  if (discounts.length > 0) {
    chips.push({ key: "max_discount_pct", text: `Trần giảm giá · ${discounts.length} SKU`, setBy: discounts[0].set_by });
  }
  const costs = Object.values(rules.product_cost).filter((item) => item.set_by);
  if (costs.length > 0) {
    chips.push({ key: "product_cost", text: `Giá vốn · ${costs.length} sản phẩm`, setBy: costs[0].set_by });
  }
  if (rules.max_open_cards.set_by) {
    chips.push({ key: "max_open_cards", text: `≤ ${String(rules.max_open_cards.value)} thẻ mở cùng lúc`, setBy: rules.max_open_cards.set_by });
  }
  if (rules.auto_levers.set_by && Array.isArray(rules.auto_levers.value)) {
    const levers = (rules.auto_levers.value as string[]).map((lever) => LEVER_LABELS[lever] ?? lever);
    chips.push({ key: "auto_levers", text: `Tự thực thi: ${levers.join(", ") || "không"}`, setBy: rules.auto_levers.set_by });
  }
  if (rules.content_tone?.set_by && typeof rules.content_tone.value === "string") {
    chips.push({ key: "content_tone", text: `Giọng văn: ${rules.content_tone.value}`, setBy: rules.content_tone.set_by });
  }
  if (rules.banned_terms?.set_by && Array.isArray(rules.banned_terms.value)) {
    chips.push({
      key: "banned_terms",
      text: `${(rules.banned_terms.value as string[]).length} từ không được dùng`,
      setBy: rules.banned_terms.set_by,
    });
  }
  if (rules.protected_terms.set_by && Array.isArray(rules.protected_terms.value)) {
    chips.push({
      key: "protected_terms",
      text: `${(rules.protected_terms.value as string[]).length} từ không được sửa`,
      setBy: rules.protected_terms.set_by,
    });
  }
  return chips;
}

function RulesChips({ rules, onOpenRules }: { readonly rules: ShopRules | null; readonly onOpenRules: () => void }) {
  const chips = ruleChips(rules);
  return (
    <section aria-labelledby="qd-rules" className="qv-side" data-testid="rules-chips">
      <h2 className="qv-side__title" id="qd-rules">
        Quy tắc do bạn đặt
      </h2>
      <p className="qv-side__text">Juli không tự chọn các con số này.</p>
      {chips.length === 0 ? (
        <p className="qv-side__text">Chưa đặt quy tắc nào — Juli dùng mặc định.</p>
      ) : (
        <ul className="qv-side__chips">
          {chips.map((chip) => (
            <li className="qv-side__chip" key={chip.key}>
              {chip.text}
              <small> · {setByLabel(chip.setBy)}</small>
            </li>
          ))}
        </ul>
      )}
      <div className="qv-side__actions">
        <button className="qv-btn qv-btn--secondary" onClick={onOpenRules} type="button">
          Sửa quy tắc
        </button>
      </div>
    </section>
  );
}
