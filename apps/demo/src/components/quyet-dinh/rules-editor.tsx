"use client";

import { useId, useState, type ReactNode } from "react";

import { QdApiError } from "../../lib/quyet-dinh/client-types";
import { LEVER_LABELS, RULE_LABELS, TEAM_TOGGLE_LABEL, bandMetricLabel, setByLabel } from "../../lib/quyet-dinh/copy";
import {
  OFF_API_ERROR_COPY,
  OFF_API_FIELDS,
  OFF_API_SAMPLE_NOTE,
  OFF_API_SECTION_LEDE,
  OFF_API_SECTION_TITLE,
  displayOffApiValue,
  formatLiveSlot,
  liveSlots,
  parseLiveSchedule,
  type OffApiRuleKey,
} from "../../lib/quyet-dinh/off-api-rules";
import { vnDate } from "../../lib/quyet-dinh/timeline";
import type { RuleKey, RuleValueItem, SetBy, ShopRules } from "../../lib/quyet-dinh/types";

/**
 * The rules editor (ADR-109 d.12, operator phase). Every rule of the shop's
 * rule store with its current value, who set it ("Đội ngũ Juli đặt" /
 * "Bạn đặt" / "Mặc định") and when. "Điền thay Seller (đội ngũ Juli)" makes
 * every save carry `set_by: "team"`; off, it is `"seller"`. A value the
 * backend refuses (422) is shown inline under its row, in Vietnamese.
 *
 * P14-F adds the "Thông tin TikTok không cung cấp" group: the fields no TikTok
 * API gives Juli. Editable when signed in; the signed-out sample passes
 * `offApiReadOnly` and shows its sample values as text.
 */

export interface RulesEditorProps {
  readonly rules: ShopRules;
  readonly onSave: (ruleKey: RuleKey, value: unknown, setBy: SetBy, scopeRef: string | null) => Promise<void>;
  readonly onDelete: (ruleKey: RuleKey, scopeRef: string | null) => Promise<void>;
  readonly onClose?: () => void;
  readonly headingLevel?: 2 | 3;
  /** Signed-out sample: the P14-F fields are shown, not edited. */
  readonly offApiReadOnly?: boolean;
  /** Juli Ops (D25.14): every value is written as the team's; no toggle. */
  readonly fixedSetBy?: SetBy;
}

/** 422 → the rule's own range, in the seller's words (the backend's text is English). */
export const RULE_ERROR_COPY: Readonly<Record<RuleKey, string>> = Object.freeze({
  stability_band: "Ngưỡng phải lớn hơn 0 và không quá 100 %.",
  product_cost: "Giá vốn phải là số từ 0 trở lên, kèm mã sản phẩm.",
  min_margin_pct: "Biên lợi nhuận phải từ 0 đến dưới 100 %.",
  max_discount_pct: "Trần giảm giá phải từ 0 đến 100 %, kèm mã SKU.",
  max_open_cards: "Số thẻ mở cùng lúc phải là số nguyên từ 5 đến 30.",
  auto_levers: "Chỉ chọn trong Tiêu đề, Mô tả, Thuộc tính, Ảnh. Giá không bao giờ được tự thực thi.",
  protected_terms: "Tối đa 200 từ, mỗi từ không quá 100 ký tự.",
  content_tone: "Giọng văn cần có nội dung, tối đa 300 ký tự.",
  banned_terms: "Tối đa 50 từ, mỗi từ không quá 100 ký tự.",
  ...OFF_API_ERROR_COPY,
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
  help,
}: {
  readonly label: string;
  readonly item: RuleValueItem | null | undefined;
  readonly children: ReactNode;
  readonly error: string | null;
  readonly testId: string;
  readonly help?: string;
}) {
  return (
    <div className="qd-rule" data-testid={testId}>
      <div className="qd-rule__label">
        <span>{label}</span>
        <span className="qd-rule__by">{provenance(item)}</span>
      </div>
      {help ? <p className="qd-muted qd-rule__help">{help}</p> : null}
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
  help,
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
  readonly help?: string;
}) {
  const inputId = useId();
  const initial = item?.set_by && item.value !== null && item.value !== undefined ? String(item.value) : "";
  const [draft, setDraft] = useState(initial);
  const { error, saving, save } = useRowSaver(ruleKey);
  return (
    <RuleRow
      error={error}
      help={help}
      item={item}
      label={label}
      testId={`rule-${ruleKey}${scopeRef ? `-${scopeRef}` : ""}`}
    >
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
  help,
}: {
  readonly ruleKey: "product_cost" | "max_discount_pct" | "sku_cost";
  readonly entries: Readonly<Record<string, RuleValueItem>>;
  readonly scopeLabel: string;
  readonly suffix: string;
  readonly setBy: SetBy;
  readonly onSave: RulesEditorProps["onSave"];
  readonly onDelete: RulesEditorProps["onDelete"];
  readonly help?: string;
}) {
  const [scope, setScope] = useState("");
  const [value, setValue] = useState("");
  const { error, saving, save } = useRowSaver(ruleKey);
  const scopeId = useId();
  const valueId = useId();
  const list = Object.entries(entries).filter(([, item]) => item.set_by);
  return (
    <RuleRow error={error} help={help} item={list[0]?.[1] ?? null} label={RULE_LABELS[ruleKey]} testId={`rule-${ruleKey}`}>
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

type FieldProps = {
  readonly rules: ShopRules;
  readonly setBy: SetBy;
  readonly onSave: RulesEditorProps["onSave"];
  readonly onDelete: RulesEditorProps["onDelete"];
};

const OFF_API_HELP: Readonly<Record<OffApiRuleKey, string>> = Object.freeze(
  Object.fromEntries(OFF_API_FIELDS.map((field) => [field.key, field.help])) as Record<OffApiRuleKey, string>,
);

function ClearButton({
  item,
  saving,
  onClear,
}: {
  readonly item: RuleValueItem | null | undefined;
  readonly saving: boolean;
  readonly onClear: () => void;
}) {
  if (!item?.set_by) return null;
  return (
    <button className="qd-rule__clear" disabled={saving} onClick={onClear} type="button">
      Bỏ đặt
    </button>
  );
}

function CampaignOptIn({ rules, setBy, onSave, onDelete }: FieldProps) {
  const item = rules.joins_platform_campaigns;
  const selectId = useId();
  const [draft, setDraft] = useState(item?.set_by ? (item.value === true ? "yes" : "no") : "");
  const { error, saving, save } = useRowSaver("joins_platform_campaigns");
  const label = RULE_LABELS.joins_platform_campaigns;
  return (
    <RuleRow
      error={error}
      help={OFF_API_HELP.joins_platform_campaigns}
      item={item}
      label={label}
      testId="rule-joins_platform_campaigns"
    >
      <label className="qd-sr" htmlFor={selectId}>
        {label}
      </label>
      <select className="qd-input" id={selectId} onChange={(event) => setDraft(event.target.value)} value={draft}>
        <option value="">Chưa chọn</option>
        <option value="yes">Có</option>
        <option value="no">Không</option>
      </select>
      <button
        className="btn-secondary qd-rule__save"
        disabled={saving}
        onClick={() =>
          void save(async () => {
            if (!draft) throw new Error("vi:Chọn Có hoặc Không.");
            await onSave("joins_platform_campaigns", draft === "yes", setBy, null);
          })
        }
        type="button"
      >
        Lưu
      </button>
      <ClearButton item={item} onClear={() => void save(() => onDelete("joins_platform_campaigns", null))} saving={saving} />
    </RuleRow>
  );
}

function TextAreaRule({
  ruleKey,
  item,
  initial,
  placeholder,
  toValue,
  setBy,
  onSave,
  onDelete,
}: {
  readonly ruleKey: "platform_campaign_note" | "live_schedule";
  readonly item: RuleValueItem | null | undefined;
  readonly initial: string;
  readonly placeholder: string;
  readonly toValue: (text: string) => unknown;
  readonly setBy: SetBy;
  readonly onSave: RulesEditorProps["onSave"];
  readonly onDelete: RulesEditorProps["onDelete"];
}) {
  const areaId = useId();
  const [draft, setDraft] = useState(initial);
  const { error, saving, save } = useRowSaver(ruleKey);
  const label = RULE_LABELS[ruleKey];
  return (
    <RuleRow error={error} help={OFF_API_HELP[ruleKey]} item={item} label={label} testId={`rule-${ruleKey}`}>
      <label className="qd-sr" htmlFor={areaId}>
        {label}
      </label>
      <textarea
        className="qd-input qd-textarea"
        id={areaId}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={placeholder}
        rows={3}
        value={draft}
      />
      <button
        className="btn-secondary qd-rule__save"
        disabled={saving}
        onClick={() => void save(() => onSave(ruleKey, toValue(draft), setBy, null))}
        type="button"
      >
        Lưu
      </button>
      <ClearButton item={item} onClear={() => void save(() => onDelete(ruleKey, null))} saving={saving} />
    </RuleRow>
  );
}

const MAX_OPEN_CARDS_HELP =
  "Từ 5 đến 30, mặc định 30. Mỗi ngày Juli thêm tối đa 5 thẻ mới (3 Juli làm, 1 Seller Center, 1 nội dung), 25 thẻ mỗi tuần.";
const CONTENT_TONE_MAX = 300;
const BANNED_TERMS_MAX = 50;

/** D24.21 (5): the voice Juli's video / LIVE scripts follow ("Giọng văn", "Từ không được dùng"). */
function ContentVoiceFields({ rules, setBy, onSave, onDelete }: FieldProps) {
  const tone = rules.content_tone;
  const banned = rules.banned_terms;
  const toneId = useId();
  const bannedId = useId();
  const [toneDraft, setToneDraft] = useState(tone?.set_by && typeof tone.value === "string" ? tone.value : "");
  const [bannedDraft, setBannedDraft] = useState(
    banned?.set_by && Array.isArray(banned.value) ? (banned.value as string[]).join("\n") : "",
  );
  const toneSaver = useRowSaver("content_tone");
  const bannedSaver = useRowSaver("banned_terms");
  return (
    <fieldset className="qd-rules-editor__group" data-testid="rules-content-voice">
      <legend>Nội dung video / LIVE</legend>
      <p className="qd-muted">Juli viết kịch bản theo giọng văn này và không dùng các từ bạn cấm (cả khi sửa tiêu đề, mô tả).</p>
      <RuleRow
        error={toneSaver.error}
        help={`Ví dụ: thân thiện, xưng mình, gọi khách là bạn. Tối đa ${CONTENT_TONE_MAX} ký tự.`}
        item={tone}
        label={RULE_LABELS.content_tone}
        testId="rule-content_tone"
      >
        <label className="qd-sr" htmlFor={toneId}>
          {RULE_LABELS.content_tone}
        </label>
        <textarea
          className="qd-input qd-textarea"
          id={toneId}
          maxLength={CONTENT_TONE_MAX}
          onChange={(event) => setToneDraft(event.target.value)}
          placeholder="Thân thiện, xưng mình, gọi khách là bạn"
          rows={2}
          value={toneDraft}
        />
        <button
          className="btn-secondary qd-rule__save"
          disabled={toneSaver.saving}
          onClick={() =>
            void toneSaver.save(async () => {
              if (!toneDraft.trim()) throw new Error("vi:Nhập giọng văn, hoặc bấm Bỏ đặt.");
              await onSave("content_tone", toneDraft.trim(), setBy, null);
            })
          }
          type="button"
        >
          Lưu
        </button>
        <ClearButton item={tone} onClear={() => void toneSaver.save(() => onDelete("content_tone", null))} saving={toneSaver.saving} />
      </RuleRow>
      <RuleRow
        error={bannedSaver.error}
        help={`Mỗi dòng một từ, tối đa ${BANNED_TERMS_MAX} từ. Juli không đưa các từ này vào kịch bản, tiêu đề hay mô tả.`}
        item={banned}
        label={RULE_LABELS.banned_terms}
        testId="rule-banned_terms"
      >
        <label className="qd-sr" htmlFor={bannedId}>
          {RULE_LABELS.banned_terms}
        </label>
        <textarea
          className="qd-input qd-textarea"
          id={bannedId}
          onChange={(event) => setBannedDraft(event.target.value)}
          placeholder="Mỗi dòng một từ"
          rows={3}
          value={bannedDraft}
        />
        <button
          className="btn-secondary qd-rule__save"
          disabled={bannedSaver.saving}
          onClick={() =>
            void bannedSaver.save(async () => {
              const terms = bannedDraft.split("\n").map((term) => term.trim()).filter(Boolean);
              if (terms.length > BANNED_TERMS_MAX) throw new Error(`vi:Tối đa ${BANNED_TERMS_MAX} từ.`);
              await onSave("banned_terms", terms, setBy, null);
            })
          }
          type="button"
        >
          Lưu
        </button>
        <ClearButton item={banned} onClear={() => void bannedSaver.save(() => onDelete("banned_terms", null))} saving={bannedSaver.saving} />
      </RuleRow>
    </fieldset>
  );
}

function OffApiFields({ rules, setBy, onSave, onDelete }: FieldProps) {
  const number = (
    ruleKey: "default_gross_margin_pct" | "default_max_discount_pct" | "program_fee_pct" | "target_roas" | "gmv_max_daily_budget",
    suffix: string,
    placeholder: string,
  ) => (
    <NumberRule
      help={OFF_API_HELP[ruleKey]}
      item={rules[ruleKey]}
      label={RULE_LABELS[ruleKey]}
      onDelete={onDelete}
      onSave={onSave}
      placeholder={placeholder}
      ruleKey={ruleKey}
      scopeRef={null}
      setBy={setBy}
      suffix={suffix}
    />
  );
  const note = rules.platform_campaign_note;
  return (
    <>
      <ScopedRule
        entries={rules.sku_cost ?? {}}
        help={OFF_API_HELP.sku_cost}
        onDelete={onDelete}
        onSave={onSave}
        ruleKey="sku_cost"
        scopeLabel="Mã SKU TikTok"
        setBy={setBy}
        suffix="₫/sản phẩm"
      />
      {number("default_gross_margin_pct", "%", "35")}
      {number("default_max_discount_pct", "%", "15")}
      {number("program_fee_pct", "%", "4")}
      <CampaignOptIn onDelete={onDelete} onSave={onSave} rules={rules} setBy={setBy} />
      <TextAreaRule
        initial={note?.set_by && typeof note.value === "string" ? note.value : ""}
        item={note}
        onDelete={onDelete}
        onSave={onSave}
        placeholder="Ví dụ: 11.11 — giảm 15 % cho 5 sản phẩm chủ lực"
        ruleKey="platform_campaign_note"
        setBy={setBy}
        toValue={(text) => {
          if (!text.trim()) throw new Error("vi:Nhập ghi chú, hoặc bấm Bỏ đặt.");
          return text.trim();
        }}
      />
      {number("target_roas", "lần (GMV ÷ chi phí QC)", "6")}
      {number("gmv_max_daily_budget", "₫/ngày", "500000")}
      <TextAreaRule
        initial={liveSlots(rules.live_schedule).map(formatLiveSlot).join("\n")}
        item={rules.live_schedule}
        onDelete={onDelete}
        onSave={onSave}
        placeholder="T2 T4 T6 20:00-22:00"
        ruleKey="live_schedule"
        setBy={setBy}
        toValue={(text) => {
          const slots = parseLiveSchedule(text);
          if (slots.length === 0) throw new Error("vi:Nhập ít nhất một khung giờ, hoặc bấm Bỏ đặt.");
          return slots;
        }}
      />
    </>
  );
}

function OffApiReadOnly({ rules }: { readonly rules: ShopRules }) {
  return (
    <>
      <p className="demo-notice" data-testid="off-api-sample-note">
        {OFF_API_SAMPLE_NOTE}
      </p>
      <dl className="qd-rule__readonly">
        {OFF_API_FIELDS.map((field) => (
          <div className="qd-rule" data-testid={`rule-${field.key}`} key={field.key}>
            <dt className="qd-rule__label">{field.label}</dt>
            <dd>
              <span>{displayOffApiValue(field.key, rules)}</span>
              <span className="qd-muted qd-rule__help"> · {field.help}</span>
            </dd>
          </div>
        ))}
      </dl>
    </>
  );
}

export function RulesEditor({
  rules,
  onSave,
  onDelete,
  onClose,
  headingLevel = 2,
  offApiReadOnly = false,
  fixedSetBy,
}: RulesEditorProps) {
  const [team, setTeam] = useState(false);
  const setBy: SetBy = fixedSetBy ?? (team ? "team" : "seller");
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

      {fixedSetBy ? null : (
        <label className="qd-toggle">
          <input checked={team} onChange={(event) => setTeam(event.target.checked)} type="checkbox" />
          <span>{TEAM_TOGGLE_LABEL}</span>
        </label>
      )}
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
          help={MAX_OPEN_CARDS_HELP}
          placeholder="30"
          ruleKey="max_open_cards"
          scopeRef={null}
          setBy={setBy}
          suffix="thẻ (5–30)"
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

      <ContentVoiceFields onDelete={onDelete} onSave={onSave} rules={rules} setBy={setBy} />

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

      <fieldset className="qd-rules-editor__group" data-testid="rules-off-api">
        <legend>{OFF_API_SECTION_TITLE}</legend>
        <p className="qd-muted">{OFF_API_SECTION_LEDE}</p>
        {offApiReadOnly ? (
          <OffApiReadOnly rules={rules} />
        ) : (
          <OffApiFields onDelete={onDelete} onSave={onSave} rules={rules} setBy={setBy} />
        )}
      </fieldset>
    </section>
  );
}
