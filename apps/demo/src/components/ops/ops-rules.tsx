"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { createOpsRulesFetch } from "../../lib/ops/view-fetch";
import { deleteShopRule, fetchShopRules, putShopRule } from "../../lib/quyet-dinh/api-client";
import { RULE_LABELS } from "../../lib/quyet-dinh/copy";
import type { RuleKey, RuleValueItem, ShopRules } from "../../lib/quyet-dinh/types";
import { readAuthSession } from "../../lib/supabase-auth";
import { RulesEditor } from "../quyet-dinh/rules-editor";
import { ConfirmDialog } from "./ops-confirm";
import { C, card } from "./ops-shell";

/** A rule value in words for the before → after dialog. */
export function fmtRuleValue(value: unknown): string {
  if (value === null || value === undefined) return "Chưa đặt";
  if (typeof value === "boolean") return value ? "Có" : "Không";
  if (typeof value === "number") return String(value).replace(".", ",");
  if (Array.isArray(value)) return value.map((v) => (typeof v === "object" ? JSON.stringify(v) : String(v))).join(", ") || "Trống";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function currentValue(rules: ShopRules | null, key: RuleKey, scope: string | null): unknown {
  const entry = (rules as unknown as Record<string, unknown> | null)?.[key];
  if (!entry || typeof entry !== "object") return null;
  if (scope !== null) return ((entry as Record<string, RuleValueItem | undefined>)[scope] ?? null)?.value ?? null;
  return (entry as RuleValueItem).value ?? null;
}

type Pending = {
  readonly title: string;
  readonly confirmLabel: string;
  readonly row: { k: string; before: string; after: string };
  readonly run: () => Promise<void>;
  readonly resolve: () => void;
  readonly reject: (e: unknown) => void;
};

/**
 * D25.14: the shop's seller rules, edited by the team in Cài đặt shop with the
 * seller's own editor (every value written as "Đội ngũ Juli đặt", audited).
 * The seller later sees and keeps editing the same rules on their Quy tắc page.
 * Approving cards stays the seller's; Xem như shop stays read-only.
 */
export function OpsRules({
  shopId,
  shopName,
  canEdit,
  baseFetch,
}: {
  readonly shopId: string;
  readonly shopName?: string;
  readonly canEdit: boolean;
  readonly baseFetch?: typeof fetch;
}) {
  const fetchImpl = useMemo(() => createOpsRulesFetch({ shopId, baseFetch }), [shopId, baseFetch]);
  const [rules, setRules] = useState<ShopRules | null>(null);
  const [failed, setFailed] = useState(false);
  // D27.5: every rule save / unset asks before → after first.
  const [pending, setPending] = useState<Pending | null>(null);
  const auth = useMemo(() => ({ token: readAuthSession()?.accessToken ?? "", shopId, fetchImpl }), [shopId, fetchImpl]);

  const load = useCallback(() => {
    fetchShopRules(auth)
      .then(setRules)
      .catch(() => setFailed(true));
  }, [auth]);

  useEffect(() => {
    load();
  }, [load]);

  const ask = (key: RuleKey, scope: string | null, after: string, title: string, confirmLabel: string, run: () => Promise<void>) =>
    new Promise<void>((resolve, reject) => {
      const label = `${RULE_LABELS[key] ?? key}${scope ? ` · ${scope}` : ""}`;
      setPending({ title, confirmLabel, row: { k: label, before: fmtRuleValue(currentValue(rules, key, scope)), after }, run, resolve, reject });
    });

  return (
    <div data-testid="ops-rules" style={card}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Quy tắc</h2>
      <span style={{ fontSize: 12, color: C.muted2 }}>
        Đội ngũ đặt trước, seller xem và sửa tiếp trong Quy tắc của mình. Mọi thay đổi được ghi nhật ký.
      </span>
      {failed ? <p role="alert">Không tải được Quy tắc.</p> : null}
      {rules ? (
        <fieldset disabled={!canEdit} style={{ border: 0, margin: 0, padding: 0, minWidth: 0 }}>
          <RulesEditor
            fixedSetBy="team"
            headingLevel={3}
            key={JSON.stringify(rules)}
            onDelete={(key, scope) =>
              ask(key, scope, "Mặc định", `Bỏ quy tắc của ${shopName ?? "shop"}?`, "Về mặc định", async () => {
                await deleteShopRule(auth, key, scope);
                load();
              })
            }
            onSave={(key, value, _setBy, scope) =>
              ask(key, scope, fmtRuleValue(value), `Lưu quy tắc cho ${shopName ?? "shop"}?`, "Xác nhận lưu", async () => {
                await putShopRule(auth, key, value, "team", scope);
                load();
              })
            }
            rules={rules}
          />
        </fieldset>
      ) : null}
      {pending ? (
        <ConfirmDialog
          confirmLabel={pending.confirmLabel}
          note="Seller thấy giá trị mới trong Quy tắc của mình. Nhật ký ghi 1 dòng."
          onCancel={() => {
            setPending(null);
            pending.resolve();
          }}
          onConfirm={async () => {
            setPending(null);
            // The editor shows a refused value inline under its row (RulesEditor).
            try {
              await pending.run();
              pending.resolve();
            } catch (e) {
              pending.reject(e);
            }
          }}
          rows={[pending.row]}
          title={pending.title}
        />
      ) : null}
    </div>
  );
}
