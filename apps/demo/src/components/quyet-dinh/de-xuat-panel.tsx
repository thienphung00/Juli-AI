"use client";

import { ConfirmDialog } from "@juli/ui";
import { useState } from "react";

import { groupStages } from "../../lib/quyet-dinh/batch";
import {
  BANDS_MISSING_BODY,
  BANDS_MISSING_PROMPT,
  LEVER_LABELS,
  MANUAL_CARD_NOTE,
  RULE_BASED_ESTIMATE,
  bandMetricLabel,
  setByLabel,
} from "../../lib/quyet-dinh/copy";
import { batchCards, type CompactCard, type DecisionGroup } from "../../lib/quyet-dinh/grouping";
import { bandsAreSet, setBands, type ShopRules } from "../../lib/quyet-dinh/types";
import { compactMoney, num } from "../../lib/vn-format";
import { FiveStageStepper } from "./five-stage-stepper";

/**
 * Đề xuất (ADR-109 d.6, d.10–12; the video's P2 screen): cards grouped by
 * stream × weak stage, a header per group with its own five-stage stepper
 * and "Duyệt N thẻ / Sửa", and a right column with the seller's stability
 * bands ("Giữ ổn định") and "Quy tắc do bạn đặt". "Duyệt N thẻ" stays
 * blocked until a band is set (d.11: ask before the first run).
 */

export interface DeXuatPanelProps {
  readonly groups: readonly DecisionGroup[];
  readonly rules: ShopRules | null;
  readonly rulesStatus: "loading" | "error" | "ready";
  /** Cards already approved this visit (their runs exist). */
  readonly approvedIds: ReadonlySet<string>;
  readonly droppedIds: ReadonlySet<string>;
  readonly busy: boolean;
  readonly progress: string | null;
  readonly onApprove: (cardIds: readonly string[]) => void;
  readonly onDrop: (cardId: string) => void;
  readonly onOpenRules: () => void;
}

type Pending = { readonly cardIds: readonly string[]; readonly title: string; readonly body: string };

export function DeXuatPanel({
  groups,
  rules,
  rulesStatus,
  approvedIds,
  droppedIds,
  busy,
  progress,
  onApprove,
  onDrop,
  onOpenRules,
}: DeXuatPanelProps) {
  const [pending, setPending] = useState<Pending | null>(null);
  const bandsSet = bandsAreSet(rules);
  const excluded = new Set([...approvedIds, ...droppedIds]);

  return (
    <div className="qd-dx">
      <div className="qd-dx__groups">
        {groups.map((group) => {
          const visible = group.cards.filter((card) => !droppedIds.has(card.id));
          if (visible.length === 0) return null;
          const runnable = batchCards(group, excluded);
          const executableTotal = group.cards.filter((card) => card.executable && !droppedIds.has(card.id)).length;
          const approved = group.cards.filter((card) => approvedIds.has(card.id)).length;
          const blockReason = !bandsSet
            ? rulesStatus === "loading"
              ? "Đang tải quy tắc của shop…"
              : BANDS_MISSING_PROMPT
            : runnable.length === 0
              ? "Không còn thẻ nào Juli tự thực hiện được trong nhóm này."
              : null;
          const headingId = `qd-group-${group.key.replace(/[^a-z0-9]/gi, "-")}`;
          return (
            <section aria-labelledby={headingId} className="qd-group" data-testid="decision-group" key={group.key}>
              <div className="qd-group__head card">
                <FiveStageStepper label={`Tiến trình · ${group.title}`} states={groupStages(approved, executableTotal)} />
                <div className="qd-group__target">
                  <div>
                    <h2 className="qd-group__title" id={headingId}>
                      {group.title}
                    </h2>
                    {group.metric ? (
                      <p className="qd-group__goal">
                        Mục tiêu · nâng {group.metric}
                        {group.streamLabel ? ` ${group.streamLabel}` : ""}
                      </p>
                    ) : null}
                  </div>
                  {group.gmvPerMonth !== null ? (
                    <div className="qd-group__gmv" data-testid="group-gmv">
                      <span className="qd-group__gmv-label">GMV dự kiến</span>
                      <strong>+{compactMoney(group.gmvPerMonth)}/tháng</strong>
                      <span className="qd-group__gmv-note">{RULE_BASED_ESTIMATE}</span>
                    </div>
                  ) : null}
                </div>
                <div className="qd-group__actions">
                  <button
                    aria-describedby={blockReason ? `${headingId}-block` : undefined}
                    className="btn-primary"
                    disabled={busy || blockReason !== null}
                    onClick={() =>
                      setPending({
                        cardIds: runnable.map((card) => card.id),
                        title: `Duyệt ${runnable.length} thẻ?`,
                        body: `Juli tạo ${runnable.length} lượt chạy và thực hiện lần lượt từng thẻ, không bao giờ hai thay đổi cùng lúc trên một sản phẩm. Mỗi lượt vẫn dừng lại để bạn xác nhận trước khi ghi lên TikTok Shop.`,
                      })
                    }
                    type="button"
                  >
                    Duyệt {runnable.length} thẻ
                  </button>
                  <button className="btn-secondary" onClick={onOpenRules} type="button">
                    Sửa
                  </button>
                  {blockReason ? (
                    <p className="qd-group__block" id={`${headingId}-block`}>
                      {blockReason}
                    </p>
                  ) : null}
                </div>
              </div>
              <ul className="qd-cards">
                {visible.map((card) => (
                  <li key={card.id}>
                    <CompactCardView
                      approved={approvedIds.has(card.id)}
                      blocked={!bandsSet || busy}
                      card={card}
                      onApprove={() =>
                        setPending({
                          cardIds: [card.id],
                          title: "Duyệt thẻ này?",
                          body: "Juli tạo một lượt chạy cho sản phẩm này. Lượt chạy dừng lại để bạn xác nhận trước khi ghi lên TikTok Shop.",
                        })
                      }
                      onDrop={() => onDrop(card.id)}
                    />
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
        {progress ? (
          <p className="qd-progress" role="status">
            {progress}
          </p>
        ) : null}
      </div>

      <aside aria-label="Quy tắc của shop" className="qd-dx__side">
        <StabilityCard onOpenRules={onOpenRules} rules={rules} rulesStatus={rulesStatus} />
        <RulesChips onOpenRules={onOpenRules} rules={rules} />
      </aside>

      <ConfirmDialog
        confirmLabel="Duyệt"
        description={pending?.body ?? ""}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (pending) onApprove(pending.cardIds);
          setPending(null);
        }}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        open={pending !== null}
        title={pending?.title ?? ""}
      />
    </div>
  );
}

function CompactCardView({
  card,
  approved,
  blocked,
  onApprove,
  onDrop,
}: {
  readonly card: CompactCard;
  readonly approved: boolean;
  readonly blocked: boolean;
  readonly onApprove: () => void;
  readonly onDrop: () => void;
}) {
  return (
    <article
      aria-label={card.name}
      className={`card qd-card${card.executable ? "" : " qd-card--manual"}`}
      data-decision-id={card.id}
      data-testid="compact-card"
    >
      <header className="qd-card__head">
        <p className="qd-card__name">
          {card.code ? (
            <span className="qd-card__code" title={card.code}>
              {card.code.length > 8 ? `…${card.code.slice(-6)}` : card.code}
            </span>
          ) : null}
          <span>{card.name}</span>
        </p>
        {card.mainKpi ? <span className="qd-card__kpi">KPI chính · {card.mainKpi}</span> : null}
      </header>
      <dl className="qd-card__facts">
        <dt>Lý do</dt>
        <dd>{card.reason ?? "—"}</dd>
        <dt>Mã TikTok</dt>
        <dd>{card.tiktokDiagnosis}</dd>
        <dt>Đòn bẩy</dt>
        <dd className="qd-card__lever">{card.lever ?? "—"}</dd>
      </dl>
      {card.change ? <p className="qd-card__change">{card.change}</p> : null}
      <footer className="qd-card__foot">
        {!card.executable ? (
          <span className="qd-card__manual">{MANUAL_CARD_NOTE}</span>
        ) : approved ? (
          <span className="badge badge-success">Đã duyệt · xem Đang thực hiện</span>
        ) : (
          <button className="btn-secondary qd-card__btn" disabled={blocked} onClick={onApprove} type="button">
            Duyệt thẻ này
          </button>
        )}
        {!approved ? (
          <button className="qd-card__drop" onClick={onDrop} type="button">
            Bỏ
          </button>
        ) : null}
      </footer>
    </article>
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
    <section aria-labelledby="qd-stability" className="card qd-side-card" data-testid="stability-card">
      <h2 className="qd-side-card__title" id="qd-stability">
        Giữ ổn định
      </h2>
      {rulesStatus === "loading" ? (
        <p className="qd-muted">Đang tải quy tắc…</p>
      ) : rulesStatus === "error" ? (
        <p className="qd-muted" role="alert">
          Không tải được quy tắc của shop. Juli chưa chạy thẻ nào cho tới khi đọc được ngưỡng.
        </p>
      ) : bands.length === 0 ? (
        <div className="qd-bands-missing" role="status">
          <p className="qd-bands-missing__title">{BANDS_MISSING_PROMPT}</p>
          <p className="qd-muted">{BANDS_MISSING_BODY}</p>
          <button className="btn-primary" onClick={onOpenRules} type="button">
            Đặt ngưỡng
          </button>
        </div>
      ) : (
        <>
          <p className="qd-muted">
            Ngày thứ 7, chỉ số nào lệch quá ngưỡng thì Juli hỏi bạn có hoàn tác không.
          </p>
          <ul className="qd-chips">
            {bands.map((band) => (
              <li className="qd-chip qd-chip--lock" key={band.metric} title={setByLabel(band.setBy)}>
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
    chips.push({ key: "min_margin_pct", text: `Biên lợi nhuận ≥ ${num(Number(rules.min_margin_pct.value), 0)} %`, setBy: rules.min_margin_pct.set_by });
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
  if (rules.protected_terms.set_by && Array.isArray(rules.protected_terms.value)) {
    chips.push({ key: "protected_terms", text: `${(rules.protected_terms.value as string[]).length} từ không được sửa`, setBy: rules.protected_terms.set_by });
  }
  return chips;
}

function RulesChips({ rules, onOpenRules }: { readonly rules: ShopRules | null; readonly onOpenRules: () => void }) {
  const chips = ruleChips(rules);
  return (
    <section aria-labelledby="qd-rules" className="card qd-side-card" data-testid="rules-chips">
      <h2 className="qd-side-card__title" id="qd-rules">
        Quy tắc do bạn đặt
      </h2>
      <p className="qd-muted">Juli không tự chọn các con số này.</p>
      {chips.length === 0 ? (
        <p className="qd-muted">Chưa đặt quy tắc nào — Juli dùng mặc định.</p>
      ) : (
        <ul className="qd-chips">
          {chips.map((chip) => (
            <li className="qd-chip" key={chip.key}>
              {chip.text}
              <span className="qd-chip__by"> · {setByLabel(chip.setBy)}</span>
            </li>
          ))}
        </ul>
      )}
      <button className="btn-secondary" onClick={onOpenRules} type="button">
        Sửa quy tắc
      </button>
    </section>
  );
}
