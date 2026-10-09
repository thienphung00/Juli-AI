"use client";

import { useId, useState, type ReactNode } from "react";

import { QdApiError } from "../../lib/quyet-dinh/client-types";
import { LEVER_LABELS, RULE_LABELS, TEAM_TOGGLE_LABEL, bandMetricLabel, setByLabel } from "../../lib/quyet-dinh/copy";
import { vnDate } from "../../lib/quyet-dinh/timeline";
import type { RuleKey, RuleValueItem, SetBy, ShopRules } from "../../lib/quyet-dinh/types";

/**
 * The rules editor (ADR-109 d.12, operator phase). Every rule of the shop's
 * rule store with its current value, who set it ("Đội ngũ Juli đặt" /
 * "Bạn đặt" / "Mặc định") and when. "Điền thay Seller (đội ngũ Juli)" makes
 * every save carry `set_by: "team"`; off, it is `"seller"`. A value the
 * backend refuses (422) is shown inline under its row, in Vietnamese.
 */

export interface RulesEditorProps {
  readonly rules: ShopRules;
  readonly onSave: (ruleKey: RuleKey, value: unknown, setBy: SetBy, scopeRef: string | null) => Promise<void>;
  readonly onDelete: (ruleKey: RuleKey, scopeRef: string | null) => Promise<void>;
  readonly onClose?: () => void;
  readonly headingLevel?: 2 | 3;
}

/** 422 → the rule's own range, in the seller's words (the backend's text is English). */
export const RULE_ERROR_COPY: Readonly<Record<RuleKey, string>> = Object.freeze({
  stability_band: "Ngưỡng phải lớn hơn 0 và không quá 100 %.",
  product_cost: "Giá vốn phải là số từ 0 trở lên, kèm mã sản phẩm.",
  min_margin_pct: "Biên lợi nhuận phải từ 0 đến dưới 100 %.",
  max_discount_pct: "Trần giảm giá phải từ 0 đến 100 %, kèm mã SKU.",
  max_open_cards: "Số thẻ mở cùng lúc phải là số nguyên từ 1 đến 5.",
  auto_levers: "Chỉ chọn trong Tiêu đề, Mô tả, Thuộc tính, Ảnh. Giá không bao giờ được tự thực thi.",
  protected_terms: "Tối đa 200 từ, mỗi từ không quá 100 ký tự.",
});

function describeError(ruleKey: RuleKey, error: unknown): string {
  if (error instanceof QdApiError) {
    if (error.status === 422) return RULE_ERROR_COPY[ruleKey];
    if (error.status === 404) return "Quy tắc này chưa được đặt.";
    return `Chưa lưu được (lỗi ${error.status}). Vui lòng thử lại.`;
  }
  if (error instanceof Error && error.message.startsWith("vi:")) return error.message.slice(3);
  return "Không thể kết nối. Vui lòng kiểm tra mạng và thử lại.";
}

function parseNumber(raw: string): number {
  const value = Number(raw.trim().replace(",", "."));
  if (!raw.trim() || !Number.isFinite(value)) throw new Error("vi:Nhập một số.");
  return value;
}

function provenance(item: RuleValueItem | null | undefined): string {
  if (!item || !item.set_by) return "Mặc định";
  return `${setByLabel(item.set_by)}${item.set_at ? ` · ${vnDate(item.set_at)}` : ""}`;
}

type Saver = (run: () => Promise<void>) => Promise<void>;

function RuleRow({
  label,
  item,
  children,
  error,
  testId,
}: {
  readonly label: string;
  readonly item: RuleValueItem | null | undefined;
  readonly children: ReactNode;
  readonly error: string | null;
  readonly testId: string;
}) {
  return (
    <div className="qd-rule" data-testid={testId}>
      <div className="qd-rule__label">
        <span>{label}</span>
        <span className="qd-rule__by">{provenance(item)}</span>
      </div>
      <div className="qd-rule__control">{children}</div>
      {error ? (
        <p className="qd-rule__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function useRowSaver(ruleKey: RuleKey): { error: string | null; saving: boolean; save: Saver } {
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const save: Saver = async (run) => {
    setSaving(true);
    setError(null);
    try {
      await run();
    } catch (caught) {
      setError(describeError(ruleKey, caught));
    } finally {
      setSaving(false);
    }
  };
  return { error, saving, save };
}

function NumberRule({
  ruleKey,
  scopeRef,
  label,
  item,
  suffix,
  placeholder,
  setBy,
  onSave,
  onDelete,
}: {
  readonly ruleKey: RuleKey;
  readonly scopeRef: string | null;
  readonly label: string;
  readonly item: RuleValueItem | null | undefined;
  readonly suffix: string;
  readonly placeholder: string;
  readonly setBy: SetBy;
  readonly onSave: RulesEditorProps["onSave"];
  readonly onDelete: RulesEditorProps["onDelete"];
}) {
  const inputId = useId();
  const initial = item?.set_by && item.value !== null && item.value !== undefined ? String(item.value) : "";
  const [draft, setDraft] = useState(initial);
  const { error, saving, save } = useRowSaver(ruleKey);
  return (
    <RuleRow error={error} item={item} label={label} testId={`rule-${ruleKey}${scopeRef ? `-${scopeRef}` : ""}`}>
      <label className="qd-sr" htmlFor={inputId}>
        {label}
      </label>
      <input
        className="qd-input"
        id={inputId}
        inputMode="decimal"
        onChange={(event) => setDraft(event.target.value)}
        placeholder={placeholder}
        value={draft}
      />
      <span className="qd-rule__suffix">{suffix}</span>
      <button
        className="btn-secondary qd-rule__save"
        disabled={saving}
        onClick={() =>
          void save(async () => {
            const value = parseNumber(draft);
            await onSave(ruleKey, value, setBy, scopeRef);
          })
        }
        type="button"
      >
        Lưu
      </button>
      {item?.set_by ? (
        <button
          className="qd-rule__clear"
          disabled={saving}
          onClick={() => void save(() => onDelete(ruleKey, scopeRef))}
          type="button"
        >
          Bỏ đặt
        </button>
      ) : null}
    </RuleRow>
  );
}

function ScopedRule({
  ruleKey,
  entries,
  scopeLabel,
  suffix,
  setBy,
  onSave,
  onDelete,
}: {
  readonly ruleKey: "product_cost" | "max_discount_pct";
  readonly entries: Readonly<Record<string, RuleValueItem>>;
  readonly scopeLabel: string;
  readonly suffix: string;
  readonly setBy: SetBy;
  readonly onSave: RulesEditorProps["onSave"];
  readonly onDelete: RulesEditorProps["onDelete"];
}) {
  const [scope, setScope] = useState("");
  const [value, setValue] = useState("");
  const { error, saving, save } = useRowSaver(ruleKey);
  const scopeId = useId();
  const valueId = useId();
  const list = Object.entries(entries).filter(([, item]) => item.set_by);
  return (
    <RuleRow error={error} item={list[0]?.[1] ?? null} label={RULE_LABELS[ruleKey]} testId={`rule-${ruleKey}`}>
      {list.length > 0 ? (
        <ul className="qd-rule__entries">
          {list.map(([ref, item]) => (
            <li key={ref}>
              <span>
                {scopeLabel} {ref}: {String(item.value)} {suffix}
              </span>
              <span className="qd-rule__by"> · {provenance(item)}</span>
              <button
                className="qd-rule__clear"
                disabled={saving}
                onClick={() => void save(() => onDelete(ruleKey, ref))}
                type="button"
              >
                Bỏ đặt
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="qd-muted">Chưa đặt.</p>
      )}
      <div className="qd-rule__add">
        <label htmlFor={scopeId}>{scopeLabel}</label>
        <input className="qd-input" id={scopeId} onChange={(event) => setScope(event.target.value)} value={scope} />
        <label htmlFor={valueId}>Giá trị ({suffix})</label>
        <input
          className="qd-input"
          id={valueId}
          inputMode="decimal"
          onChange={(event) => setValue(event.target.value)}
          value={value}
        />
        <button
          className="btn-secondary qd-rule__save"
          disabled={saving}
          onClick={() =>
            void save(async () => {
              await onSave(ruleKey, parseNumber(value), setBy, scope.trim() || null);
              setScope("");
              setValue("");
            })
          }
          type="button"
        >
          Thêm
        </button>
      </div>
    </RuleRow>
  );
}

export function RulesEditor({ rules, onSave, onDelete, onClose, headingLevel = 2 }: RulesEditorProps) {
  const [team, setTeam] = useState(false);
  const setBy: SetBy = team ? "team" : "seller";
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const levers = Array.isArray(rules.auto_levers.value) ? (rules.auto_levers.value as string[]) : [];
  const [leverDraft, setLeverDraft] = useState<readonly string[]>(levers);
  const leverSaver = useRowSaver("auto_levers");
  const terms = Array.isArray(rules.protected_terms.value) ? (rules.protected_terms.value as string[]) : [];
  const [termsDraft, setTermsDraft] = useState(terms.join("\n"));
  const termsSaver = useRowSaver("protected_terms");
  const termsId = useId();

  return (
    <section aria-labelledby="qd-rules-editor" className="card qd-rules-editor" data-testid="rules-editor">
      <div className="qd-rules-editor__head">
        <div>
          <Heading className="qd-side-card__title" id="qd-rules-editor">
            Quy tắc của shop
          </Heading>
          <p className="qd-muted">Mọi con số ở đây do bạn (hoặc đội ngũ Juli thay bạn) đặt — Juli không tự chọn.</p>
        </div>
        {onClose ? (
          <button className="btn-secondary" onClick={onClose} type="button">
            Đóng
          </button>
        ) : null}
      </div>

      <label className="qd-toggle">
        <input checked={team} onChange={(event) => setTeam(event.target.checked)} type="checkbox" />
        <span>{TEAM_TOGGLE_LABEL}</span>
      </label>
      <p className="qd-muted" data-testid="set-by-mode">
        Giá trị bạn lưu sẽ ghi: {setByLabel(setBy)}
      </p>

      <fieldset className="qd-rules-editor__group">
        <legend>{RULE_LABELS.stability_band} (±%)</legend>
        <p className="qd-muted">Chỉ số không phải mục tiêu được phép lệch bao nhiêu trước khi Juli hỏi hoàn tác. Gợi ý ±3 %.</p>
        {rules.band_metrics.map((metric) => (
          <NumberRule
            item={rules.stability_band[metric]}
            key={metric}
            label={bandMetricLabel(metric)}
            onDelete={onDelete}
            onSave={onSave}
            placeholder="3"
            ruleKey="stability_band"
            scopeRef={metric}
            setBy={setBy}
            suffix="± %"
          />
        ))}
      </fieldset>

      <fieldset className="qd-rules-editor__group">
        <legend>Thẻ và thực thi</legend>
        <NumberRule
          item={rules.max_open_cards}
          label={RULE_LABELS.max_open_cards}
          onDelete={onDelete}
          onSave={onSave}
          placeholder="5"
          ruleKey="max_open_cards"
          scopeRef={null}
          setBy={setBy}
          suffix="thẻ (1–5)"
        />
        <RuleRow error={leverSaver.error} item={rules.auto_levers} label={RULE_LABELS.auto_levers} testId="rule-auto_levers">
          <div className="qd-rule__checks">
            {rules.listing_levers.map((lever) => (
              <label key={lever}>
                <input
                  checked={leverDraft.includes(lever)}
                  onChange={(event) =>
                    setLeverDraft((current) =>
                      event.target.checked ? [...current, lever] : current.filter((item) => item !== lever),
                    )
                  }
                  type="checkbox"
                />
                {LEVER_LABELS[lever] ?? lever}
              </label>
            ))}
          </div>
          <span className="qd-muted">Giá không bao giờ tự thực thi.</span>
          <button
            className="btn-secondary qd-rule__save"
            disabled={leverSaver.saving}
            onClick={() => void leverSaver.save(() => onSave("auto_levers", [...leverDraft], setBy, null))}
            type="button"
          >
            Lưu
          </button>
        </RuleRow>
        <RuleRow error={termsSaver.error} item={rules.protected_terms} label={RULE_LABELS.protected_terms} testId="rule-protected_terms">
          <label className="qd-sr" htmlFor={termsId}>
            {RULE_LABELS.protected_terms}
          </label>
          <textarea
            className="qd-input qd-textarea"
            id={termsId}
            onChange={(event) => setTermsDraft(event.target.value)}
            placeholder="Mỗi dòng một từ"
            rows={3}
            value={termsDraft}
          />
          <button
            className="btn-secondary qd-rule__save"
            disabled={termsSaver.saving}
            onClick={() =>
              void termsSaver.save(() =>
                onSave(
                  "protected_terms",
                  termsDraft.split("\n").map((term) => term.trim()).filter(Boolean),
                  setBy,
                  null,
                ),
              )
            }
            type="button"
          >
            Lưu
          </button>
        </RuleRow>
      </fieldset>

      <fieldset className="qd-rules-editor__group">
        <legend>Giá và biên lợi nhuận</legend>
        <p className="qd-muted">Chưa đặt thì Juli không đề xuất giá và xếp hạng theo doanh thu.</p>
        <NumberRule
          item={rules.min_margin_pct}
          label={RULE_LABELS.min_margin_pct}
          onDelete={onDelete}
          onSave={onSave}
          placeholder="30"
          ruleKey="min_margin_pct"
          scopeRef={null}
          setBy={setBy}
          suffix="%"
        />
        <ScopedRule
          entries={rules.product_cost}
          onDelete={onDelete}
          onSave={onSave}
          ruleKey="product_cost"
          scopeLabel="Mã sản phẩm TikTok"
          setBy={setBy}
          suffix="₫/sản phẩm"
        />
        <ScopedRule
          entries={rules.max_discount_pct}
          onDelete={onDelete}
          onSave={onSave}
          ruleKey="max_discount_pct"
          scopeLabel="Mã SKU"
          setBy={setBy}
          suffix="%"
        />
      </fieldset>
    </section>
  );
}
